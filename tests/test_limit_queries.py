from uuid import uuid4

import pytest
from sqlalchemy import event, select

from conftest import token
from loyalty_service.errors import DomainError
from loyalty_service.models import PromoCode
from loyalty_service.promotions.service import check_limits
from test_api import add_code, order, setup_plan


@pytest.mark.parametrize('global_limit,expected_queries', [(None, 1), (4, 2)])
def test_limit_checks_use_only_required_bounded_queries(system, global_limit, expected_queries):
    plan = setup_plan(system)
    add_code(system, max_redemptions=global_limit, per_user_limit=3)
    assert order(system, plan, 'WELCOME').status_code == 201
    with system[1]() as session:
        code = session.scalar(select(PromoCode))
        statements = []
        def observe(conn, cursor, statement, parameters, context, executemany):
            if 'promo_redemptions' in statement.lower():
                statements.append(statement.lower())
        event.listen(session.bind, 'before_cursor_execute', observe)
        try:
            check_limits(session, code, system[2])
        finally:
            event.remove(session.bind, 'before_cursor_execute', observe)
    assert len(statements) == expected_queries
    assert all('limit' in sql for sql in statements)
    assert all('count(' not in sql for sql in statements)


@pytest.mark.parametrize('scope', ['global', 'user'])
def test_limit_threshold_for_several_matching_records(system, scope):
    plan = setup_plan(system)
    add_code(system, max_redemptions=3 if scope == 'global' else None,
        per_user_limit=3 if scope == 'user' else 10)
    client, _, uid, _, _ = system
    for i in range(3):
        owner = uid if scope == 'user' else uuid4()
        response = client.post('/api/v1/orders', headers={
            'Authorization': 'Bearer '+token(owner), 'Idempotency-Key': str(i)},
            json={'plan_id': plan, 'promo_code': 'WELCOME'})
        assert response.status_code == 201, response.text
    with system[1]() as session:
        code = session.scalar(select(PromoCode))
        expected = 'PROMO_LIMIT_REACHED' if scope == 'global' else 'PROMO_USER_LIMIT_REACHED'
        with pytest.raises(DomainError) as exc:
            check_limits(session, code, uid)
        assert exc.value.code == expected
