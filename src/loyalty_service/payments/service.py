from sqlalchemy import select

from loyalty_service.db import lock_user
from loyalty_service.errors import DomainError
from loyalty_service.models import AuditLog, Order, Payment, PromoCode, PromoRedemption, utcnow
from loyalty_service.subscriptions.service import grant_subscription


def locked_order(session, order_id):
    owner = session.scalar(select(Order.user_id).where(Order.id == order_id))
    if owner is None:
        raise DomainError('ORDER_NOT_FOUND', 'Заказ не найден', 404)
    lock_user(session, owner)
    order = session.scalar(select(Order).where(Order.id == order_id).with_for_update().execution_options(populate_existing=True))
    if order.promo_code_id:
        session.scalar(select(PromoCode).where(PromoCode.id == order.promo_code_id).with_for_update())
    return order


def cancel_order(session, order):
    order.status = 'CANCELLED'
    payment = session.scalar(select(Payment).where(Payment.order_id == order.id))
    if payment:
        payment.status = 'CANCELLED'
    redemption = session.scalar(select(PromoRedemption).where(PromoRedemption.order_id == order.id))
    if redemption:
        redemption.status = 'RELEASED'


def resolve_payment(session, order_id, outcome, actor_id, now=None):
    order = locked_order(session, order_id)
    now = now or utcnow()
    desired = 'PAID' if outcome == 'succeeded' else 'FAILED'
    if order.status == desired:
        return order, None
    if order.status != 'PENDING':
        raise DomainError('PAYMENT_STATE_CONFLICT', 'Платёж уже завершён с другим результатом')
    if order.expires_at <= now:
        cancel_order(session, order)
        session.add(AuditLog(actor_id=actor_id, action='payment.expired', target_id=order.id))
        # Caller commits cancellation before returning an error to the client.
        return order, DomainError('PAYMENT_EXPIRED', 'Тестовый платёж отменён по истечении срока')
    payment = session.scalar(select(Payment).where(Payment.order_id == order.id))
    if payment is None:
        raise DomainError('PAYMENT_NOT_FOUND', 'Платёж не найден', 404)
    order.status = desired
    payment.status = 'SUCCEEDED' if outcome == 'succeeded' else 'FAILED'
    redemption = session.scalar(select(PromoRedemption).where(PromoRedemption.order_id == order.id))
    if redemption:
        redemption.status = 'APPLIED' if outcome == 'succeeded' else 'RELEASED'
    if outcome == 'succeeded':
        grant_subscription(session, order, now)
    session.add(AuditLog(actor_id=actor_id, action='payment.'+outcome, target_id=order.id))
    session.flush()
    return order, None


def cleanup_expired(session, now=None, batch_size=100):
    now = now or utcnow()

    ids = session.scalars(select(Order.id).where(Order.status == 'PENDING', Order.expires_at <= now)
        .order_by(Order.expires_at).limit(batch_size)).all()
    session.rollback()
    count = 0
    for order_id in ids:
        try:
            order = locked_order(session, order_id)
            if order.status == 'PENDING' and order.expires_at <= now:
                cancel_order(session, order)
                session.add(AuditLog(actor_id=order.user_id, action='payment.expired.cleanup', target_id=order.id,
                    details={'source': 'cleanup'}))
                count += 1
            session.commit()
        except Exception:
            session.rollback()
            raise
    return count
