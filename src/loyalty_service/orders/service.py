import hashlib
import json
from datetime import timedelta

from sqlalchemy import select

from loyalty_service.db import lock_user
from loyalty_service.errors import DomainError
from loyalty_service.models import AuditLog, Order, PromoRedemption, utcnow
from loyalty_service.payments.adapter import MockPaymentAdapter
from loyalty_service.promotions.service import get_plan, preview
from loyalty_service.subscriptions.service import grant_subscription


def create_order(session, user_id, payload, idempotency_key, actor_id, reason=None, reservation_minutes=15):
    lock_user(session, user_id)
    body = {'plan_id': str(payload.plan_id), 'promo_code': payload.promo_code,
        'actor_id': str(actor_id), 'reason': reason}
    fingerprint = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    previous = session.scalar(select(Order).where(Order.user_id == user_id, Order.idempotency_key == idempotency_key))
    if previous:
        if previous.fingerprint != fingerprint:
            raise DomainError('IDEMPOTENCY_CONFLICT', 'Ключ уже использован для другого запроса')
        return previous, False
    code = None
    if payload.promo_code:
        plan, code, price = preview(session, user_id, payload.plan_id, payload.promo_code, locked=True)
    else:
        plan = get_plan(session, payload.plan_id)
        price = {'base_price_kopecks': plan.price_kopecks, 'final_price_kopecks': plan.price_kopecks,
            'duration_days': plan.duration_days, 'currency': 'RUB'}
    now = utcnow()
    order = Order(user_id=user_id, plan_id=plan.id, promo_code_id=code.id if code else None,
        **price, idempotency_key=idempotency_key, fingerprint=fingerprint,
        expires_at=now+timedelta(minutes=reservation_minutes))
    session.add(order)
    session.flush()
    redemption = None
    if code:
        redemption = PromoRedemption(promo_code_id=code.id, user_id=user_id, order_id=order.id,
            expires_at=order.expires_at, actor_id=actor_id, reason=reason)
        session.add(redemption)
    if order.final_price_kopecks == 0:
        order.status = 'COMPLETED_FREE'
        if redemption:
            redemption.status = 'APPLIED'
        grant_subscription(session, order, now)
    else:
        session.add(MockPaymentAdapter().create(order))
    if reason is not None:
        session.add(AuditLog(actor_id=actor_id, action='order.admin_applied', target_id=order.id,
            reason=reason, details={'user_id': str(user_id)}))
    session.flush()
    return order, True


def get_order(session, order_id, user):
    order = session.get(Order, order_id)
    if order is None or (order.user_id != user.user_id and not user.is_admin):
        raise DomainError('ORDER_NOT_FOUND', 'Заказ не найден', 404)
    return order
