from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from loyalty_service.auth import Principal, get_current_user
from loyalty_service.db import get_session
from loyalty_service.errors import DomainError
from loyalty_service.models import Plan, utcnow
from loyalty_service.promotions.schemas import PreviewInput
from loyalty_service.promotions.service import preview, record_attempt
from .common import serialize

router = APIRouter(prefix='/api/v1', tags=['Promotions'])


@router.get('/plans')
def plans(session: Session = Depends(get_session)):
    return [serialize(plan) for plan in session.scalars(select(Plan).where(Plan.active.is_(True)).order_by(Plan.created_at))]


@router.post('/promocodes/preview')
def preview_code(payload: PreviewInput, request: Request, user: Principal = Depends(get_current_user),
                 session: Session = Depends(get_session)):
    try:
        _, _, result = preview(session, user.user_id, payload.plan_id, payload.code, utcnow())
        record_attempt(session, user.user_id, payload.code, True, None, request.state.request_id)
        session.commit()
        return result
    except DomainError as exc:
        session.rollback()
        record_attempt(session, user.user_id, payload.code, False, exc.code, request.state.request_id)
        session.commit()
        raise
