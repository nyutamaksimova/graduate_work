from dataclasses import dataclass
from secrets import compare_digest
from uuid import UUID

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from .errors import DomainError

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    user_id: UUID
    role: str
    is_superuser: bool = False

    @property
    def is_admin(self):
        return self.is_superuser or self.role in {'ADMIN', 'SUPER_ADMIN'}


def get_current_user(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    if credentials is None:
        raise DomainError('UNAUTHORIZED', 'Требуется access JWT', 401)
    settings = request.app.state.settings
    try:
        data = jwt.decode(credentials.credentials, settings.jwt_secret,
            algorithms=[settings.jwt_algorithm], options={'require_exp': True, 'require_sub': True})
        if data.get('type') == 'refresh' or not isinstance(data.get('role'), str):
            raise ValueError('access token required')
        if not isinstance(data.get('is_superuser', False), bool):
            raise ValueError('invalid superuser claim')
        return Principal(UUID(data['sub']), data['role'], data.get('is_superuser', False))
    except (JWTError, ValueError, KeyError, TypeError):
        raise DomainError('UNAUTHORIZED', 'Недействительный или просроченный access JWT', 401)


def require_admin(user: Principal = Depends(get_current_user)):
    if not user.is_admin:
        raise DomainError('FORBIDDEN', 'Нужны права администратора', 403)
    return user


def require_internal_token(request: Request):
    value = request.headers.get('X-Service-Token', '')
    if not compare_digest(value.encode(), request.app.state.settings.internal_api_token.encode()):
        raise DomainError('UNAUTHORIZED', 'Неверный сервисный токен', 401)
