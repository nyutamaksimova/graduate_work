from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from loyalty_service.errors import DomainError
from loyalty_service.promotions.rules import calculate_price, normalize_code, validate_code


def test_normalization():
    assert normalize_code('  welcome  ') == 'WELCOME'


@pytest.mark.parametrize('kind,value,expected', [
    ('FIXED_PRICE', 0, 0), ('FIXED_PRICE', 19900, 19900),
    ('PERCENT_DISCOUNT', 1, 100), ('PERCENT_DISCOUNT', 50, 51),
    ('PERCENT_DISCOUNT', 100, 0), ('TRIAL', 0, 0),
])
def test_prices(kind, value, expected):
    assert calculate_price(101, kind, value) == expected


@pytest.mark.parametrize('field,value,error', [
    ('active', False, 'PROMO_INACTIVE'),
    ('valid_from', 'future', 'PROMO_NOT_STARTED'),
    ('valid_until', 'past', 'PROMO_EXPIRED'),
    ('plan_id', 'other', 'PROMO_PLAN_NOT_ALLOWED'),
    ('assigned_user_id', 'other', 'PROMO_USER_NOT_ELIGIBLE'),
])
def test_rejections(field, value, error):
    now = datetime.now(UTC)
    code = SimpleNamespace(active=True, valid_from=now-timedelta(days=1),
        valid_until=now+timedelta(days=1), plan_id=None, assigned_user_id=None)
    if value == 'future':
        value = now + timedelta(seconds=1)
    elif value == 'past':
        value = now
    setattr(code, field, value)
    with pytest.raises(DomainError) as exc:
        validate_code(code, 'plan', 'user', now)
    assert exc.value.code == error
