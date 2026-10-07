import secrets

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from loyalty_service.errors import DomainError
from loyalty_service.models import AuditLog, Plan, PromoAttempt, PromoCode, PromoRedemption, utcnow
from .rules import calculate_price, normalize_code, validate_code

USED = ('RESERVED', 'APPLIED')


def get_plan(session, plan_id):
    plan = session.get(Plan, plan_id)
    if plan is None or not plan.active:
        raise DomainError('PLAN_NOT_FOUND', 'Тариф не найден или отключён', 404)
    return plan


def check_limits(session, code, user_id):
    query = select(func.count()).select_from(PromoRedemption).where(
        PromoRedemption.promo_code_id == code.id, PromoRedemption.status.in_(USED))
    total = session.scalar(query)
    if code.max_redemptions is not None and total >= code.max_redemptions:
        raise DomainError('PROMO_LIMIT_REACHED', 'Общий лимит промокода исчерпан')
    if session.scalar(query.where(PromoRedemption.user_id == user_id)) >= code.per_user_limit:
        raise DomainError('PROMO_USER_LIMIT_REACHED', 'Вы уже использовали этот промокод')
    if code.benefit_type == 'TRIAL':
        trial = session.scalar(select(PromoRedemption.id).join(PromoCode).where(
            PromoRedemption.user_id == user_id, PromoRedemption.status.in_(USED),
            PromoCode.benefit_type == 'TRIAL').limit(1))
        if trial:
            raise DomainError('TRIAL_ALREADY_USED', 'Пробный период уже использован')


def preview(session, user_id, plan_id, code_value, now=None, locked=False):
    plan = get_plan(session, plan_id)
    query = select(PromoCode).where(PromoCode.code == normalize_code(code_value))
    if locked:
        query = query.with_for_update()
    code = session.scalar(query)
    now = now or utcnow()
    validate_code(code, plan_id, user_id, now)
    check_limits(session, code, user_id)
    return plan, code, {
        'base_price_kopecks': plan.price_kopecks,
        'final_price_kopecks': calculate_price(plan.price_kopecks, code.benefit_type, code.benefit_value),
        'currency': 'RUB',
        'duration_days': code.trial_days if code.benefit_type == 'TRIAL' else plan.duration_days,
    }


def record_attempt(session, user_id, code, success, error_code, request_id):
    session.add(PromoAttempt(user_id=user_id, code=normalize_code(code), success=success,
        error_code=error_code, request_id=request_id))


def create_code(session, actor_id, payload):
    if payload.plan_id:
        get_plan(session, payload.plan_id)
    code = PromoCode(**payload.model_dump())
    session.add(code)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        raise DomainError('PROMO_CODE_EXISTS', 'Такой код уже существует')
    session.add(AuditLog(actor_id=actor_id, action='promo.created', target_id=code.id))
    return code


def generate_codes(session, actor_id, payload):
    if payload.plan_id:
        get_plan(session, payload.plan_id)
    result = []
    alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
    data = payload.model_dump(exclude={'count', 'prefix'})
    for _ in range(payload.count):
        for attempt in range(10):
            value = payload.prefix.upper() + ''.join(secrets.choice(alphabet) for _ in range(12))
            try:
                with session.begin_nested():
                    code = PromoCode(code=value, **data)
                    session.add(code)
                    session.flush()
                result.append(code)
                session.add(AuditLog(actor_id=actor_id, action='promo.generated', target_id=code.id))
                break
            except IntegrityError:
                if attempt == 9:
                    raise DomainError('GENERATION_FAILED', 'Не удалось сгенерировать уникальные коды', 503)
    return result
