from datetime import timedelta

from sqlalchemy import select

from loyalty_service.models import Subscription, SubscriptionGrant


def grant_subscription(session, order, now):
    existing = session.scalar(select(SubscriptionGrant).where(SubscriptionGrant.order_id == order.id))
    subscription = session.scalar(select(Subscription).where(Subscription.user_id == order.user_id).with_for_update())
    if existing:
        return subscription
    start = max(now, subscription.ends_at) if subscription else now
    end = start + timedelta(days=order.duration_days)
    if subscription is None:
        subscription = Subscription(user_id=order.user_id, starts_at=start, ends_at=end)
        session.add(subscription)
    else:
        if subscription.ends_at <= now:
            subscription.starts_at = start
        subscription.ends_at = end
    session.add(SubscriptionGrant(order_id=order.id, user_id=order.user_id, starts_at=start, ends_at=end))
    session.flush()
    return subscription


def get_entitlement(session, user_id, now):
    subscription = session.scalar(select(Subscription).where(Subscription.user_id == user_id))
    return {'user_id': user_id, 'active': bool(subscription and subscription.starts_at <= now < subscription.ends_at),
        'starts_at': subscription.starts_at if subscription else None,
        'ends_at': subscription.ends_at if subscription else None}
