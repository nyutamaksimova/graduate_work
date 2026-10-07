from decimal import Decimal, ROUND_HALF_UP
import re

from loyalty_service.errors import DomainError


def normalize_code(value: str) -> str:
    return value.strip().upper()


def validated_code(value: str) -> str:
    value = normalize_code(value)
    if not re.fullmatch(r'[A-Z0-9_-]{1,64}', value):
        raise ValueError('Используйте 1–64 латинских буквы, цифры, _ и -')
    return value


def calculate_price(base_price: int, benefit_type: str, benefit_value: int) -> int:
    if benefit_type == 'TRIAL':
        return 0
    if benefit_type == 'FIXED_PRICE':
        return benefit_value
    return int((Decimal(base_price) * (100-benefit_value) / 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def validate_code(code, plan_id, user_id, now):
    if code is None:
        raise DomainError('PROMO_NOT_FOUND', 'Промокод не найден', 404)
    checks = [
        (not code.active, 'PROMO_INACTIVE', 'Промокод отключён'),
        (code.valid_from is not None and now < code.valid_from, 'PROMO_NOT_STARTED', 'Акция ещё не началась'),
        (code.valid_until is not None and now >= code.valid_until, 'PROMO_EXPIRED', 'Промокод истёк'),
        (code.plan_id is not None and code.plan_id != plan_id, 'PROMO_PLAN_NOT_ALLOWED', 'Промокод не подходит к тарифу'),
        (code.assigned_user_id is not None and code.assigned_user_id != user_id, 'PROMO_USER_NOT_ELIGIBLE', 'Промокод предназначен другому пользователю'),
    ]
    for failed, error, message in checks:
        if failed:
            raise DomainError(error, message)
