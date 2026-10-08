import pytest
from sqlalchemy import event


@pytest.mark.parametrize('field', ['max_redemptions', 'per_user_limit'])
@pytest.mark.parametrize('generate', [False, True])
def test_integer_overflow_rejected_before_database(system, field, generate):
    client, sessions, _, _, admin = system
    payload = {'benefit_type': 'FIXED_PRICE', 'benefit_value': 0, field: 2147483648}
    path = '/api/v1/admin/promocodes'
    if generate:
        path += '/generate'
        payload['count'] = 1
    else:
        payload['code'] = 'LIMIT'
    engine = sessions.kw['bind']
    def no_sql(*args):
        raise AssertionError('Invalid integer reached the database')
    event.listen(engine, 'before_cursor_execute', no_sql)
    try:
        response = client.post(path, headers=admin, json=payload)
        assert response.status_code == 422
        assert response.json()['error']['code'] == 'VALIDATION_ERROR'
        assert ['body', field] in [item['location'] for item in response.json()['error']['details']]
    finally:
        event.remove(engine, 'before_cursor_execute', no_sql)


@pytest.mark.parametrize('generate', [False, True])
def test_integer_maximum_accepted(system, generate):
    client, _, _, _, admin = system
    payload = {'benefit_type': 'FIXED_PRICE', 'benefit_value': 0,
        'max_redemptions': 2147483647, 'per_user_limit': 2147483647}
    path = '/api/v1/admin/promocodes'
    if generate:
        path += '/generate'
        payload['count'] = 1
    else:
        payload['code'] = 'LIMIT'
    response = client.post(path, headers=admin, json=payload)
    assert response.status_code == 201, response.text
    code = response.json()['items'][0] if generate else response.json()
    assert code['max_redemptions'] == code['per_user_limit'] == 2147483647
