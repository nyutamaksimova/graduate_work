from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy import event

from loyalty_service.errors import DomainError
from loyalty_service.models import Order, Plan, PromoCode, PromoRedemption, Subscription, SubscriptionGrant, utcnow
from loyalty_service.orders.schemas import OrderInput
from loyalty_service.orders.service import create_order
from loyalty_service.payments.service import cleanup_expired, resolve_payment

pytestmark = pytest.mark.postgres


def seed(sessions, kind='PERCENT_DISCOUNT', value=50, max_uses=1, second=False):
    with sessions() as s:
        p = Plan(name='Test', price_kopecks=49900, duration_days=30)
        s.add(p)
        s.flush()
        for name in (['ONE', 'TWO'] if second else ['ONE']):
            s.add(PromoCode(code=name, benefit_type=kind, benefit_value=value,
                trial_days=7 if kind == 'TRIAL' else None, max_redemptions=max_uses, per_user_limit=10))
        s.commit()
        return p.id


def concurrent_calls(function):
    barrier = Barrier(2)
    def run(i):
        barrier.wait(timeout=10)
        return function(i)
    with ThreadPoolExecutor(max_workers=2) as pool:
        return list(pool.map(run, [0, 1]))


def test_single_use_has_one_winner(pg_sessions):
    plan = seed(pg_sessions)
    def buy(i):
        with pg_sessions() as s:
            uid = uuid4()
            try:
                create_order(s, uid, OrderInput(plan_id=plan, promo_code='ONE'), str(uuid4()), uid)
                s.commit()
                return 'ok'
            except DomainError as exc:
                s.rollback()
                return exc.code
    assert sorted(concurrent_calls(buy)) == ['PROMO_LIMIT_REACHED', 'ok']


def test_parallel_trials_different_codes(pg_sessions):
    plan = seed(pg_sessions, 'TRIAL', 0, second=True)
    uid = uuid4()
    def buy(i):
        with pg_sessions() as s:
            try:
                create_order(s, uid, OrderInput(plan_id=plan, promo_code=['ONE','TWO'][i]), str(uuid4()), uid)
                s.commit()
                return 'ok'
            except DomainError as exc:
                s.rollback()
                return exc.code
    assert sorted(concurrent_calls(buy)) == ['TRIAL_ALREADY_USED', 'ok']


def test_parallel_extensions(pg_sessions):
    plan = seed(pg_sessions, 'FIXED_PRICE', 0, max_uses=None)
    uid = uuid4()
    def buy(i):
        with pg_sessions() as s:
            create_order(s, uid, OrderInput(plan_id=plan, promo_code='ONE'), str(uuid4()), uid)
            s.commit()
    concurrent_calls(buy)
    with pg_sessions() as s:
        sub = s.scalar(select(Subscription))
        assert sub.ends_at-sub.starts_at == timedelta(days=60)
        assert s.scalar(select(func.count()).select_from(SubscriptionGrant)) == 2


def test_parallel_idempotency(pg_sessions):
    plan = seed(pg_sessions)
    uid = uuid4()
    def buy(i):
        with pg_sessions() as s:
            order, created = create_order(s, uid, OrderInput(plan_id=plan), 'same', uid)
            s.commit()
            return str(order.id)
    ids = concurrent_calls(buy)
    assert ids[0] == ids[1]
    with pg_sessions() as s:
        assert s.scalar(select(func.count()).select_from(Order)) == 1


def test_cleanup_races_payment(pg_sessions):
    plan = seed(pg_sessions)
    uid = uuid4()
    with pg_sessions() as s:
        order, _ = create_order(s, uid, OrderInput(plan_id=plan, promo_code='ONE'), 'race', uid)
        order.expires_at = utcnow()-timedelta(seconds=1)
        oid = order.id
        s.commit()
    def run(i):
        with pg_sessions() as s:
            try:
                if i == 0:
                    cleanup_expired(s)
                else:
                    resolve_payment(s, oid, 'succeeded', uid)
                    s.commit()
            except DomainError:
                s.rollback()
    concurrent_calls(run)
    with pg_sessions() as s:
        assert s.get(Order, oid).status == 'CANCELLED'
        assert s.scalar(select(PromoRedemption)).status == 'RELEASED'
        assert s.scalar(select(func.count()).select_from(SubscriptionGrant)) == 0


def test_payment_clock_refreshed_after_lock_wait(pg_sessions, monkeypatch):
    import loyalty_service.payments.service as payments
    from loyalty_service.db import lock_user
    plan = seed(pg_sessions)
    uid = uuid4()
    clock = [utcnow()]
    monkeypatch.setattr(payments, 'utcnow', lambda: clock[0])
    with pg_sessions() as s:
        row, _ = create_order(s, uid, OrderInput(plan_id=plan), 'clock', uid)
        row.expires_at = clock[0]+timedelta(seconds=1)
        oid = row.id
        s.commit()
    waiting = Event()
    def observed(conn, cursor, statement, parameters, context, executemany):
        if 'pg_advisory_xact_lock' in statement:
            waiting.set()
    with pg_sessions() as holder:
        lock_user(holder, uid)
        event.listen(holder.bind, 'before_cursor_execute', observed)
        def pay():
            with pg_sessions() as s:
                row, error = payments.resolve_payment(s, oid, 'succeeded', uid)
                s.commit()
                return row.status, error.code if error else None
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(pay)
                assert waiting.wait(5)
                clock[0] += timedelta(seconds=2)
                holder.commit()
                assert future.result(timeout=10) == ('CANCELLED', 'PAYMENT_EXPIRED')
        finally:
            holder.rollback()
            event.remove(holder.bind, 'before_cursor_execute', observed)


def test_promo_clock_refreshed_after_lock_wait(pg_sessions, monkeypatch):
    import loyalty_service.orders.service as orders
    import loyalty_service.promotions.service as promotions
    plan = seed(pg_sessions)
    uid = uuid4()
    clock = [utcnow()]
    monkeypatch.setattr(orders, 'utcnow', lambda: clock[0])
    monkeypatch.setattr(promotions, 'utcnow', lambda: clock[0], raising=False)
    with pg_sessions() as s:
        code = s.scalar(select(PromoCode))
        code.valid_until = clock[0]+timedelta(seconds=1)
        cid = code.id
        s.commit()
    waiting = Event()
    def observed(conn, cursor, statement, parameters, context, executemany):
        if 'promo_codes' in statement and 'FOR UPDATE' in statement:
            waiting.set()
    with pg_sessions() as holder:
        holder.scalar(select(PromoCode).where(PromoCode.id == cid).with_for_update())
        event.listen(holder.bind, 'before_cursor_execute', observed)
        def buy():
            with pg_sessions() as s:
                try:
                    orders.create_order(s, uid, OrderInput(plan_id=plan, promo_code='ONE'), 'clock', uid)
                    s.commit()
                    return 'ok'
                except DomainError as exc:
                    s.rollback()
                    return exc.code
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(buy)
                assert waiting.wait(5)
                clock[0] += timedelta(seconds=2)
                holder.commit()
                assert future.result(timeout=10) == 'PROMO_EXPIRED'
        finally:
            holder.rollback()
            event.remove(holder.bind, 'before_cursor_execute', observed)
