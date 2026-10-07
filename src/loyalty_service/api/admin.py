from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from loyalty_service.auth import Principal, require_admin
from loyalty_service.db import get_session
from loyalty_service.errors import DomainError
from loyalty_service.models import AuditLog, Plan, PromoAttempt, PromoCode
from loyalty_service.orders.schemas import AdminOrderInput
from loyalty_service.promotions.schemas import CodeInput, CodePatch, GenerateInput, PlanInput
from loyalty_service.promotions.service import create_code, generate_codes
from .common import serialize
from .orders import submit_order

router = APIRouter(prefix='/api/v1/admin', tags=['Admin'])


@router.post('/plans', status_code=201)
def add_plan(payload: PlanInput, user: Principal = Depends(require_admin), session: Session = Depends(get_session)):
    plan = Plan(**payload.model_dump())
    session.add(plan)
    session.flush()
    session.add(AuditLog(actor_id=user.user_id, action='plan.created', target_id=plan.id))
    session.commit()
    return serialize(plan)


@router.post('/promocodes', status_code=201)
def add_code(payload: CodeInput, user: Principal = Depends(require_admin), session: Session = Depends(get_session)):
    code = create_code(session, user.user_id, payload)
    session.commit()
    return serialize(code)


@router.post('/promocodes/generate', status_code=201)
def generate(payload: GenerateInput, user: Principal = Depends(require_admin), session: Session = Depends(get_session)):
    codes = generate_codes(session, user.user_id, payload)
    session.commit()
    return {'items': [serialize(code) for code in codes]}


@router.patch('/promocodes/{code_id}')
def toggle(code_id: UUID, payload: CodePatch, user: Principal = Depends(require_admin), session: Session = Depends(get_session)):
    code = session.scalar(select(PromoCode).where(PromoCode.id == code_id).with_for_update())
    if code is None:
        raise DomainError('PROMO_NOT_FOUND', 'Промокод не найден', 404)
    code.active = payload.active
    session.add(AuditLog(actor_id=user.user_id, action='promo.toggled', target_id=code.id,
        details={'active': payload.active}))
    session.commit()
    return serialize(code)


@router.post('/users/{user_id}/orders', status_code=201)
def admin_order(user_id: UUID, payload: AdminOrderInput, request: Request, response: Response,
                idempotency_key: str = Header(min_length=1, max_length=128),
                actor: Principal = Depends(require_admin), session: Session = Depends(get_session)):
    result, created = submit_order(session, request, payload, idempotency_key, user_id, actor.user_id, payload.reason)
    response.status_code = 201 if created else 200
    return result


@router.get('/promo-attempts')
def attempts(user_id: UUID | None = None, error_code: str | None = None,
             limit: int = Query(default=50, ge=1, le=100), offset: int = Query(default=0, ge=0),
             actor: Principal = Depends(require_admin), session: Session = Depends(get_session)):
    query = select(PromoAttempt)
    if user_id is not None:
        query = query.where(PromoAttempt.user_id == user_id)
    if error_code is not None:
        query = query.where(PromoAttempt.error_code == error_code)
    total = session.scalar(select(func.count()).select_from(query.subquery()))
    rows = session.scalars(query.order_by(PromoAttempt.created_at.desc(), PromoAttempt.id).limit(limit).offset(offset))
    return {'total': total, 'items': [serialize(row) for row in rows], 'limit': limit, 'offset': offset}
