from datetime import timedelta

from sqlalchemy import select

from loyalty_service.models import Order, PromoRedemption, utcnow
from loyalty_service.payments.service import cleanup_expired
from test_api import add_code, order, resolve, setup_plan


def expire(sessions, order_id):
    from uuid import UUID
    with sessions() as s:
        row = s.get(Order, UUID(order_id))
        row.expires_at = utcnow() - timedelta(seconds=1)
        s.commit()


def test_cleanup_releases_reservation_and_rejects_late_success(system):
    plan = setup_plan(system)
    add_code(system)
    r = order(system, plan, 'WELCOME').json()
    sessions = system[1]
    expire(sessions, r['id'])
    with sessions() as s:
        assert cleanup_expired(s) == 1
        assert cleanup_expired(s) == 0
        assert s.scalar(select(PromoRedemption)).status == 'RELEASED'
    assert resolve(system, r['id'], 'succeeded').status_code == 409
    assert order(system, plan, 'WELCOME').status_code == 201


def test_nonexpired_not_cancelled(system):
    plan = setup_plan(system)
    order(system, plan)
    with system[1]() as s:
        assert cleanup_expired(s) == 0


def test_resolve_expired_commits_cancellation(system):
    plan = setup_plan(system)
    add_code(system)
    data = order(system, plan, 'WELCOME').json()
    expire(system[1], data['id'])
    assert resolve(system, data['id'], 'succeeded').json()['error']['code'] == 'PAYMENT_EXPIRED'
    with system[1]() as s:
        assert s.scalar(select(Order)).status == 'CANCELLED'
        assert s.scalar(select(PromoRedemption)).status == 'RELEASED'


def test_two_purchases_extend_access(system):
    plan = setup_plan(system)
    first = order(system, plan).json()
    assert resolve(system, first['id'], 'succeeded').status_code == 200
    client, _, _, user, _ = system
    from datetime import datetime
    end1 = datetime.fromisoformat(client.get('/api/v1/subscriptions/me', headers=user).json()['ends_at'])
    second = order(system, plan).json()
    assert resolve(system, second['id'], 'succeeded').status_code == 200
    end2 = datetime.fromisoformat(client.get('/api/v1/subscriptions/me', headers=user).json()['ends_at'])
    assert end2-end1 == timedelta(days=30)
