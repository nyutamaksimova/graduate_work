from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy import select

from loyalty_service.errors import DomainError
from loyalty_service.models import Order, PromoCode, PromoRedemption, utcnow
from loyalty_service.promotions.service import check_limits
from test_api import add_code, order, resolve, setup_plan


@pytest.mark.parametrize('scope', ['global', 'user', 'trial'])
@pytest.mark.parametrize('status,seconds,counted', [
    ('RESERVED', -3600, False), ('RESERVED', 0, False),
    ('RESERVED', 60, True), ('APPLIED', -3600, True),
    ('RELEASED', 60, False),
])
def test_limits_count_only_live_reservations(system, monkeypatch, scope, status, seconds, counted):
    plan = setup_plan(system)
    add_code(system, max_redemptions=1 if scope == 'global' else None,
        per_user_limit=1 if scope == 'user' else 10)
    assert order(system, plan, 'WELCOME').status_code == 201
    now = utcnow()
    monkeypatch.setattr('loyalty_service.promotions.service.utcnow', lambda: now)
    with system[1]() as session:
        code = session.scalar(select(PromoCode))
        redemption = session.scalar(select(PromoRedemption))
        redemption.status = status
        redemption.expires_at = now+timedelta(seconds=seconds)
        if scope == 'trial':
            # Cover the shared predicate for RESERVED trials as well, even
            # though the current free checkout confirms a trial immediately.
            code.benefit_type, code.benefit_value, code.trial_days = 'TRIAL', 0, 7
        session.flush()
        if counted:
            expected = {'global': 'PROMO_LIMIT_REACHED', 'user': 'PROMO_USER_LIMIT_REACHED',
                'trial': 'TRIAL_ALREADY_USED'}[scope]
            with pytest.raises(DomainError) as exc:
                check_limits(session, code, system[2])
            assert exc.value.code == expected
        else:
            check_limits(session, code, system[2])


def test_reuse_without_cleanup_and_expired_payment_rejected(system):
    plan = setup_plan(system)
    add_code(system)
    first = order(system, plan, 'WELCOME').json()
    with system[1]() as session:
        row = session.get(Order, UUID(first['id']))
        reservation = session.scalar(select(PromoRedemption).where(PromoRedemption.order_id == row.id))
        row.expires_at = reservation.expires_at = utcnow()-timedelta(hours=1)
        session.commit()
    client, _, _, user, _ = system
    assert client.post('/api/v1/promocodes/preview', headers=user,
        json={'plan_id': plan, 'code': 'WELCOME'}).status_code == 200
    # No cleanup runs: the old reservation is still stored as RESERVED.
    second = order(system, plan, 'WELCOME')
    assert second.status_code == 201, second.text
    assert resolve(system, first['id'], 'succeeded').json()['error']['code'] == 'PAYMENT_EXPIRED'
    assert resolve(system, second.json()['id'], 'succeeded').json()['status'] == 'PAID'
