from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from loyalty_service.auth import Principal, get_current_user, require_internal_token
from loyalty_service.db import get_session
from loyalty_service.models import utcnow
from loyalty_service.subscriptions.service import get_entitlement

router = APIRouter(tags=['Subscriptions'])


@router.get('/api/v1/subscriptions/me')
def my_subscription(user: Principal = Depends(get_current_user), session: Session = Depends(get_session)):
    return get_entitlement(session, user.user_id, utcnow())


@router.get('/internal/v1/users/{user_id}/entitlements', dependencies=[Depends(require_internal_token)])
def entitlement(user_id: UUID, session: Session = Depends(get_session)):
    return get_entitlement(session, user_id, utcnow())
