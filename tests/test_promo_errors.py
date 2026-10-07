from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from test_api import add_code, order, resolve, setup_plan


@pytest.mark.parametrize('override,expected', [
    ({'active': False}, 'PROMO_INACTIVE'),
    ({'valid_from': (datetime.now(UTC)+timedelta(days=1)).isoformat()}, 'PROMO_NOT_STARTED'),
    ({'valid_until': (datetime.now(UTC)-timedelta(days=1)).isoformat()}, 'PROMO_EXPIRED'),
    ({'assigned_user_id': str(uuid4())}, 'PROMO_USER_NOT_ELIGIBLE'),
])
def test_errors_persist(system, override, expected):
    plan = setup_plan(system)
    add_code(system, **override)
    r = order(system, plan, 'WELCOME')
    assert r.json()['error']['code'] == expected
    client, _, _, _, admin = system
    result = client.get('/api/v1/admin/promo-attempts', params={'error_code': expected}, headers=admin).json()
    assert result['total'] == 1
    assert result['items'][0]['success'] is False


def test_wrong_plan(system):
    first, second = setup_plan(system), setup_plan(system)
    add_code(system, plan_id=first)
    assert order(system, second, 'WELCOME').json()['error']['code'] == 'PROMO_PLAN_NOT_ALLOWED'


def test_disable_after_reservation_does_not_change_order(system):
    plan = setup_plan(system)
    code = add_code(system)
    data = order(system, plan, 'WELCOME').json()
    client, _, _, _, admin = system
    assert client.patch('/api/v1/admin/promocodes/'+code['id'], headers=admin, json={'active': False}).status_code == 200
    assert resolve(system, data['id'], 'succeeded').json()['final_price_kopecks'] == 24950


def test_multiuse_across_users(system):
    from conftest import token
    plan = setup_plan(system)
    add_code(system, max_redemptions=None)
    assert order(system, plan, 'WELCOME').status_code == 201
    client = system[0]
    assert client.post('/api/v1/orders', headers={
        'Authorization': 'Bearer '+token(uuid4()), 'Idempotency-Key': 'second-user'},
        json={'plan_id': plan, 'promo_code': 'WELCOME'}).status_code == 201


def test_positive_fixed_price(system):
    plan = setup_plan(system)
    add_code(system, benefit_type='FIXED_PRICE', benefit_value=9900)
    data = order(system, plan, 'WELCOME').json()
    assert data['final_price_kopecks'] == 9900
    assert data['status'] == 'PENDING'


def test_refresh_token_rejected(system):
    from jose import jwt
    from conftest import SECRET
    client, _, uid, _, _ = system
    value = jwt.encode({'sub': str(uid), 'role': 'ADMIN', 'type': 'refresh',
        'exp': datetime.now(UTC)+timedelta(minutes=10)}, SECRET, algorithm='HS256')
    assert client.get('/api/v1/subscriptions/me', headers={'Authorization': 'Bearer '+value}).status_code == 401


def test_unicode_uppercase_expansion_rejected(system):
    plan = setup_plan(system)
    assert order(system, plan, 'ß'*64).status_code == 422
    client, _, _, user, _ = system
    assert client.post('/api/v1/promocodes/preview', headers=user,
        json={'plan_id': plan, 'code': 'ß'*64}).status_code == 422
