from collections.abc import Generator

import jwt
from fastapi import Depends, Header, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.security import decode_access_token
from app.db.models import AuthSession, User
from app.services.auth_sessions import session_is_active, unauthorized
from app.services.game_sessions import GameAccess
from game_tracker import ModelBundle


def get_db(request: Request) -> Generator[Session, None, None]:
    db = request.app.state.session_factory()
    try:
        yield db
    finally:
        db.close()


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_model_bundle(request: Request) -> ModelBundle:
    return request.app.state.model_bundle


bearer = HTTPBearer(auto_error=False)


def get_optional_auth_session(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AuthSession | None:
    if credentials is None:
        if request.headers.get("Authorization"):
            raise unauthorized()
        return None
    try:
        claims = decode_access_token(credentials.credentials, settings)
    except jwt.InvalidTokenError as exc:
        raise unauthorized() from exc
    session = db.get(AuthSession, claims["sid"])
    if not session_is_active(session) or str(session.user_id) != claims["sub"] or not session.user:
        raise unauthorized()
    return session


def get_current_user(session: AuthSession | None = Depends(get_optional_auth_session)) -> User:
    if session is None:
        raise unauthorized()
    return session.user


def get_game_access(
    session: AuthSession | None = Depends(get_optional_auth_session),
    guest_token: str | None = Header(default=None, alias="X-Game-Token", max_length=128),
) -> GameAccess:
    return GameAccess(user=session.user if session else None, guest_token=guest_token)


def require_cookie_request(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> None:
    # A custom header forces cross-origin browsers to preflight. Also validate
    # Origin on the server: CORS response headers alone do not block mutations.
    origin = request.headers.get("Origin")
    if request.headers.get("X-CSRF-Protection") != "1" or (origin is not None and origin not in settings.cors_origins):
        raise HTTPException(status_code=403, detail="Untrusted authentication request.")
