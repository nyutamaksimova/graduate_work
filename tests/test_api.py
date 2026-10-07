from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from conftest import token
from loyalty_service.models import PromoRedemption, SubscriptionGrant


def setup_plan(system):
    client, _, _, _, admin = system
    r = client.post('/api/v1/admin/plans', headers=admin,
        json={'name': 'Monthly', 'price_kopecks': 49900, 'duration_days': 30})
    assert r.status_code == 201, r.text
    return r.json()['id']


def add_code(system, **overrides):
    client, _, _, _, admin = system
    data = {'code': 'WELCOME', 'benefit_type': 'PERCENT_DISCOUNT', 'benefit_value': 50,
        'max_redemptions': 1, 'per_user_limit': 1}
    data.update(overrides)
    r = client.post('/api/v1/admin/promocodes', headers=admin, json=data)
    assert r.status_code == 201, r.text
    return r.json()


def order(system, plan_id, code=None, key=None):
    client, _, _, user, _ = system
    return client.post('/api/v1/orders', headers={**user, 'Idempotency-Key': key or str(uuid4())},
        json={'plan_id': plan_id, 'promo_code': code})


def resolve(system, order_id, outcome):
    client, _, _, _, admin = system
    return client.post(f'/api/v1/admin/payments/{order_id}/resolve', headers=admin, json={'outcome': outcome})


def test_auth_and_permissions(system):
    client, _, uid, user, _ = system
    assert client.get('/api/v1/subscriptions/me').status_code == 401
    assert client.get('/api/v1/subscriptions/me', headers={'Authorization': 'Bearer '+token(uid, expired=True)}).status_code == 401
    assert client.post('/api/v1/admin/plans', headers=user, json={}).status_code == 403
    assert client.get(f'/internal/v1/users/{uid}/entitlements').status_code == 401
    assert client.get('/health').status_code == 200
    assert client.get('/ready').status_code == 200


def test_paid_purchase_and_duplicate_payment(system):
    plan = setup_plan(system)
    r = order(system, plan)
    assert r.status_code == 201, r.text
    data = r.json()
    assert data['final_price_kopecks'] == 49900
    assert data['status'] == 'PENDING'
    assert resolve(system, data['id'], 'succeeded').json()['status'] == 'PAID'
    client, sessions, uid, user, _ = system
    end = client.get('/api/v1/subscriptions/me', headers=user).json()['ends_at']
    assert resolve(system, data['id'], 'succeeded').status_code == 200
    assert client.get('/api/v1/subscriptions/me', headers=user).json()['ends_at'] == end
    assert resolve(system, data['id'], 'failed').status_code == 409
    with sessions() as s:
        assert len(s.scalars(select(SubscriptionGrant)).all()) == 1
    assert client.get(f'/internal/v1/users/{uid}/entitlements',
        headers={'X-Service-Token': 'test-internal-token'}).json()['active'] is True


def test_discount_preview_does_not_reserve(system):
    plan = setup_plan(system)
    add_code(system)
    client, sessions, _, user, _ = system
    r = client.post('/api/v1/promocodes/preview', headers=user, json={'plan_id': plan, 'code': ' welcome '})
    assert r.json()['final_price_kopecks'] == 24950
    with sessions() as s:
        assert not s.scalars(select(PromoRedemption)).all()
    r = order(system, plan, 'WELCOME')
    assert r.json()['final_price_kopecks'] == 24950
    other = order(system, plan, 'WELCOME')
    assert other.status_code == 409
    assert other.json()['error']['code'] == 'PROMO_LIMIT_REACHED'
    assert resolve(system, r.json()['id'], 'failed').status_code == 200
    assert order(system, plan, 'WELCOME').status_code == 201


@pytest.mark.parametrize('kind,value,days', [('FIXED_PRICE', 0, 30), ('TRIAL', 0, 7), ('PERCENT_DISCOUNT', 100, 30)])
def test_free_access(system, kind, value, days):
    plan = setup_plan(system)
    add_code(system, benefit_type=kind, benefit_value=value, trial_days=7 if kind == 'TRIAL' else None)
    r = order(system, plan, 'WELCOME')
    assert r.status_code == 201, r.text
    assert r.json()['status'] == 'COMPLETED_FREE'
    assert r.json()['duration_days'] == days
    client, _, _, user, _ = system
    assert client.get('/api/v1/subscriptions/me', headers=user).json()['active'] is True


def test_trial_once_across_codes(system):
    plan = setup_plan(system)
    add_code(system, benefit_type='TRIAL', benefit_value=0, trial_days=7)
    add_code(system, code='SECOND', benefit_type='TRIAL', benefit_value=0, trial_days=7)
    assert order(system, plan, 'WELCOME').status_code == 201
    r = order(system, plan, 'SECOND')
    assert r.json()['error']['code'] == 'TRIAL_ALREADY_USED'


def test_idempotency_and_ownership(system):
    plan = setup_plan(system)
    r = order(system, plan, key='same')
    assert order(system, plan, key='same').json()['id'] == r.json()['id']
    assert order(system, plan, 'OTHER', key='same').status_code == 409
    client, _, _, _, _ = system
    assert client.get('/api/v1/orders/'+r.json()['id'], headers={
        'Authorization': 'Bearer '+token(uuid4())}).status_code == 404


def test_invalid_code_logged(system):
    plan = setup_plan(system)
    assert order(system, plan, 'MISSING').json()['error']['code'] == 'PROMO_NOT_FOUND'
    client, _, _, _, admin = system
    rows = client.get('/api/v1/admin/promo-attempts', headers=admin).json()['items']
    assert rows[0]['error_code'] == 'PROMO_NOT_FOUND'


def test_user_limit(system):
    plan = setup_plan(system)
    add_code(system, max_redemptions=None)
    assert order(system, plan, 'WELCOME').status_code == 201
    assert order(system, plan, 'WELCOME').json()['error']['code'] == 'PROMO_USER_LIMIT_REACHED'


def test_admin_apply_and_generate(system):
    plan = setup_plan(system)
    add_code(system, benefit_type='FIXED_PRICE', benefit_value=0)
    client, _, uid, _, admin = system
    r = client.post(f'/api/v1/admin/users/{uid}/orders', headers={**admin, 'Idempotency-Key': 'admin-1'},
        json={'plan_id': plan, 'promo_code': 'WELCOME', 'reason': 'Support gift'})
    assert r.status_code == 201, r.text
    r = client.post('/api/v1/admin/promocodes/generate', headers=admin,
        json={'count': 10, 'prefix': 'NEW-', 'benefit_type': 'FIXED_PRICE', 'benefit_value': 9900})
    assert r.status_code == 201, r.text
    codes = [x['code'] for x in r.json()['items']]
    assert len(set(codes)) == 10
    assert all(x.startswith('NEW-') and len(x) == 16 for x in codes)


def test_payment_controls(system):
    plan = setup_plan(system)
    r = order(system, plan)
    client, _, _, user, admin = system
    url = f"/api/v1/admin/payments/{r.json()['id']}/resolve"
    assert client.post(url, headers=user, json={'outcome': 'succeeded'}).status_code == 403
    client.app.state.settings.enable_mock_payment_control = False
    assert client.post(url, headers=admin, json={'outcome': 'succeeded'}).status_code == 403


@pytest.mark.parametrize('changes', [
    {'benefit_value': 101}, {'benefit_value': 0}, {'max_redemptions': 0},
    {'valid_until': '2026-01-01T00:00:00'}, {'per_user_limit': 0},
])
def test_invalid_promo_payload(system, changes):
    client, _, _, _, admin = system
    data = {'code': 'BAD', 'benefit_type': 'PERCENT_DISCOUNT', 'benefit_value': 10, **changes}
    assert client.post('/api/v1/admin/promocodes', headers=admin, json=data).status_code == 422
