import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from redis import Redis
from sqlalchemy import func, select

from conftest import token
from loyalty_service.config import Settings
from loyalty_service.errors import DomainError
from loyalty_service.models import PromoAttempt
from loyalty_service.promo_guard import PromoGuard
from test_api import add_code, setup_plan

pytestmark = pytest.mark.redis


@pytest.fixture
def guard():
    url = os.getenv('TEST_REDIS_URL')
    if not url:
        pytest.skip('Set TEST_REDIS_URL to a dedicated test Redis')
    client = Redis.from_url(url)
    prefix = 'loyalty-test:'+uuid4().hex
    settings = Settings(jwt_secret='test-secret-for-loyalty-at-least-32-characters',
        internal_api_token='test-internal-token', promo_user_limit=2, promo_ip_limit=3,
        promo_window_seconds=60, promo_failure_threshold=2,
        promo_failure_window_seconds=300, promo_block_seconds=900)
    instance = PromoGuard(client, settings, prefix=prefix)
    yield instance
    keys = list(client.scan_iter(match=prefix+'*'))
    if keys:
        client.delete(*keys)
    client.close()


def test_user_limit_across_ips(guard):
    uid = uuid4()
    guard.admit(uid, '127.0.0.1')
    guard.admit(uid, '127.0.0.2')
    with pytest.raises(DomainError) as exc:
        guard.admit(uid, '127.0.0.3')
    assert exc.value.status_code == 429
    assert exc.value.code == 'PROMO_RATE_LIMITED'
    assert int(exc.value.headers['Retry-After']) > 0


def test_ip_limit_across_users(guard):
    for _ in range(3):
        guard.admit(uuid4(), '127.0.0.1')
    with pytest.raises(DomainError) as exc:
        guard.admit(uuid4(), '127.0.0.1')
    assert exc.value.status_code == 429


def test_failure_block_and_expiration(guard):
    uid = uuid4()
    guard.record_failure(uid, '127.0.0.1')
    guard.record_failure(uid, '127.0.0.2')
    with pytest.raises(DomainError) as exc:
        guard.admit(uid, '127.0.0.3')
    assert exc.value.code == 'PROMO_TEMPORARILY_BLOCKED'
    assert int(exc.value.headers['Retry-After']) > 60
    # Real Redis expiration, without sleeping or changing the production clock.
    for key in guard.client.scan_iter(match=guard.prefix+'*'):
        guard.client.pexpire(key, 0)
    guard.admit(uid, '127.0.0.3')


def test_ip_block_across_users(guard):
    for _ in range(2):
        guard.record_failure(uuid4(), '127.0.0.1')
    with pytest.raises(DomainError) as exc:
        guard.admit(uuid4(), '127.0.0.1')
    assert exc.value.code == 'PROMO_TEMPORARILY_BLOCKED'


def test_counters_expire_and_rejected_calls_do_not_extend_block(guard):
    uid = uuid4()
    guard.admit(uid, '127.0.0.1')
    guard.record_failure(uid, '127.0.0.1')
    assert all(0 < guard.client.ttl(key) <= 300 for key in guard.client.scan_iter(match=guard.prefix+'*'))
    guard.record_failure(uid, '127.0.0.1')
    before = {key: guard.client.pttl(key) for key in guard.client.scan_iter(match=guard.prefix+'*:block')}
    for _ in range(3):
        with pytest.raises(DomainError):
            guard.admit(uid, '127.0.0.1')
    assert all(guard.client.pttl(key) <= ttl for key, ttl in before.items())


def test_two_guard_instances_share_atomic_budget(guard):
    second = PromoGuard(guard.client, guard.settings, prefix=guard.prefix)
    uid = uuid4()
    def attempt(i):
        try:
            (guard if i % 2 else second).admit(uid, '127.0.0.1')
            return True
        except DomainError:
            return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(attempt, range(20))) == 2


def test_preview_and_orders_share_guard_before_database(system, guard):
    plan = setup_plan(system)
    client, sessions, _, user, _ = system
    client.app.state.promo_guard = guard
    preview = {'plan_id': plan, 'code': 'MISSING'}
    assert client.post('/api/v1/promocodes/preview', headers=user, json=preview).status_code == 404
    assert client.post('/api/v1/orders', headers={**user, 'Idempotency-Key': 'missing'},
        json={'plan_id': plan, 'promo_code': 'MISSING2'}).status_code == 404
    with sessions() as s:
        assert s.scalar(select(func.count()).select_from(PromoAttempt)) == 2
    # Any SQL after this point is a regression: rate rejection must precede DB work.
    from sqlalchemy import event
    def no_sql(*args):
        raise AssertionError('Blocked request reached PostgreSQL/SQLAlchemy')
    engine = sessions.kw['bind']
    event.listen(engine, 'before_cursor_execute', no_sql)
    try:
        r = client.post('/api/v1/promocodes/preview', headers=user, json=preview)
        assert r.status_code == 429
        assert r.json()['error']['code'] == 'PROMO_TEMPORARILY_BLOCKED'
        assert int(r.headers['Retry-After']) > 0
        r = client.post('/api/v1/orders', headers={**user, 'Idempotency-Key': 'other'},
            json={'plan_id': plan, 'promo_code': 'DIFFERENT'})
        assert r.status_code == 429
    finally:
        event.remove(engine, 'before_cursor_execute', no_sql)


def test_forwarded_ip_cannot_bypass_limits(system, guard):
    plan = setup_plan(system)
    client, _, _, _, _ = system
    client.app.state.promo_guard = guard
    guard.settings.promo_failure_threshold = 100
    for i in range(3):
        r = client.post('/api/v1/promocodes/preview', headers={
            'Authorization': 'Bearer '+token(uuid4()), 'X-Forwarded-For': f'10.0.0.{i}'},
            json={'plan_id': plan, 'code': 'MISSING'})
        assert r.status_code == 404
    r = client.post('/api/v1/promocodes/preview', headers={
        'Authorization': 'Bearer '+token(uuid4()), 'X-Forwarded-For': '10.0.0.100'},
        json={'plan_id': plan, 'code': 'MISSING'})
    assert r.status_code == 429


def test_without_promo_not_throttled(system, guard):
    plan = setup_plan(system)
    client, _, uid, user, _ = system
    client.app.state.promo_guard = guard
    for _ in range(2):
        guard.record_failure(uid, 'testclient')
    assert client.post('/api/v1/orders', headers={**user, 'Idempotency-Key': 'no-code'},
        json={'plan_id': plan}).status_code == 201


@pytest.mark.parametrize('endpoint', ['preview', 'order', 'admin_order'])
def test_redis_unavailable_fails_closed(system, guard, monkeypatch, endpoint):
    from redis.exceptions import ConnectionError
    plan = setup_plan(system)
    client, sessions, _, user, admin = system
    client.app.state.promo_guard = guard
    def offline(*args, **kwargs):
        raise ConnectionError('offline')
    monkeypatch.setattr(guard.client, 'eval', offline)
    from sqlalchemy import event
    engine = sessions.kw['bind']
    def no_sql(*args):
        raise AssertionError('Unprotected request reached the database')
    event.listen(engine, 'before_cursor_execute', no_sql)
    try:
        if endpoint == 'preview':
            path, body, auth = '/api/v1/promocodes/preview', {'plan_id': plan, 'code': 'MISSING'}, user
        else:
            path, body, auth = '/api/v1/orders', {'plan_id': plan, 'promo_code': 'MISSING'}, user
            if endpoint == 'admin_order':
                path, auth = f'/api/v1/admin/users/{uuid4()}/orders', admin
                body['reason'] = 'Test'
        r = client.post(path, headers={**auth, 'Idempotency-Key': str(uuid4())}, json=body)
        assert r.status_code == 503
        assert r.json()['error']['code'] == 'PROMO_PROTECTION_UNAVAILABLE'
    finally:
        event.remove(engine, 'before_cursor_execute', no_sql)


def test_successful_requests_share_endpoint_rate_budget(system, guard):
    plan = setup_plan(system)
    add_code(system, benefit_type='FIXED_PRICE', benefit_value=0, max_redemptions=None, per_user_limit=10)
    client, _, _, user, _ = system
    client.app.state.promo_guard = guard
    assert client.post('/api/v1/promocodes/preview', headers=user,
        json={'plan_id': plan, 'code': 'WELCOME'}).status_code == 200
    assert client.post('/api/v1/orders', headers={**user, 'Idempotency-Key': 'valid'},
        json={'plan_id': plan, 'promo_code': 'WELCOME'}).status_code == 201
    r = client.post('/api/v1/promocodes/preview', headers=user,
        json={'plan_id': plan, 'code': 'WELCOME'})
    assert r.status_code == 429
    assert r.json()['error']['code'] == 'PROMO_RATE_LIMITED'


def test_admin_target_change_cannot_bypass_operator_limit(system, guard):
    plan = setup_plan(system)
    client, _, _, _, admin = system
    client.app.state.promo_guard = guard
    guard.settings.promo_failure_threshold = 100
    for _ in range(2):
        r = client.post(f'/api/v1/admin/users/{uuid4()}/orders', headers={
            **admin, 'Idempotency-Key': str(uuid4())}, json={
            'plan_id': plan, 'promo_code': 'MISSING', 'reason': 'Test'})
        assert r.status_code == 404
    r = client.post(f'/api/v1/admin/users/{uuid4()}/orders', headers={
        **admin, 'Idempotency-Key': str(uuid4())}, json={
        'plan_id': plan, 'promo_code': 'MISSING', 'reason': 'Test'})
    assert r.status_code == 429


def test_block_applies_until_last_millisecond(guard):
    uid = uuid4()
    for _ in range(2):
        guard.record_failure(uid, '127.0.0.1')
    keys = list(guard.client.scan_iter(match=guard.prefix+'*:block'))
    assert len(keys) == 2
    for key in keys:
        guard.client.pexpire(key, 400)
        assert guard.client.ttl(key) == 0
    with pytest.raises(DomainError) as exc:
        guard.admit(uid, '127.0.0.1')
    assert exc.value.code == 'PROMO_TEMPORARILY_BLOCKED'
    assert exc.value.headers['Retry-After'] == '1'


def test_retry_after_includes_longer_rate_window(guard):
    uid = uuid4()
    guard.settings.promo_block_seconds = 2
    for _ in range(2):
        guard.admit(uid, '127.0.0.1')
        guard.record_failure(uid, '127.0.0.1')
    with pytest.raises(DomainError) as exc:
        guard.admit(uid, '127.0.0.1')
    assert exc.value.code == 'PROMO_TEMPORARILY_BLOCKED'
    assert int(exc.value.headers['Retry-After']) > 2


def test_rejecting_one_budget_does_not_consume_other(guard):
    guard.settings.promo_user_limit = 1
    guard.settings.promo_ip_limit = 1
    a, b = uuid4(), uuid4()
    guard.admit(a, '127.0.0.1')
    with pytest.raises(DomainError):
        guard.admit(b, '127.0.0.1')
    guard.admit(b, '127.0.0.2')
    with pytest.raises(DomainError):
        guard.admit(a, '127.0.0.3')
    guard.admit(uuid4(), '127.0.0.3')
