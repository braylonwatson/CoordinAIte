import secrets
from datetime import timedelta
from uuid import uuid4

from fastapi import HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.security import as_utc, create_access_token, hash_secret, new_secret
from app.db.models import AuthSession, User, utc_now


REFRESH_COOKIE = "coordinaite_refresh"


def unauthorized() -> HTTPException:
    return HTTPException(status_code=401, detail="Please sign in again.", headers={"WWW-Authenticate": "Bearer"})


def session_is_active(session: AuthSession | None) -> bool:
    return bool(session and session.revoked_at is None and as_utc(session.expires_at) > utc_now())


def user_response(user: User) -> dict:
    return {
        "user_id": user.id,
        "username": user.username,
        "email": user.email,
        "tier": user.tier or "free",
        "subscription_status": user.subscription_status,
    }


def token_response(session: AuthSession, settings: Settings, response: Response) -> dict:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return {
        **user_response(session.user),
        "access_token": create_access_token(session.user_id, session.id, session.expires_at, settings),
        "token_type": "bearer",
        "expires_in": min(settings.access_token_minutes * 60, max(0, int((as_utc(session.expires_at) - utc_now()).total_seconds()))),
    }


def set_refresh_cookie(response: Response, value: str, session: AuthSession, settings: Settings) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        value,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
        path="/auth",
        max_age=max(0, int((as_utc(session.expires_at) - utc_now()).total_seconds())),
    )


def clear_refresh_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        REFRESH_COOKIE,
        path="/auth",
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
    )


def begin_session(db: Session, user: User, settings: Settings, response: Response) -> dict:
    secret = new_secret()
    session = AuthSession(
        id=str(uuid4()),
        user_id=user.id,
        user=user,
        refresh_token_hash=hash_secret(secret),
        expires_at=utc_now() + timedelta(days=settings.refresh_token_days),
    )
    db.add(session)
    db.commit()
    set_refresh_cookie(response, f"{session.id}.{secret}", session, settings)
    return token_response(session, settings, response)


def find_refresh_session(db: Session, token: str | None) -> AuthSession | None:
    if not token or len(token) > 160:
        return None
    session_id, separator, secret = token.partition(".")
    if not separator or len(session_id) != 36 or not secret:
        return None
    # Lock before checking the hash, so two workers cannot use the same refresh twice.
    session = db.execute(
        select(AuthSession).where(AuthSession.id == session_id).with_for_update()
    ).scalar_one_or_none()
    if not session_is_active(session) or not secrets.compare_digest(session.refresh_token_hash, hash_secret(secret)):
        return None
    return session


def refresh_session(db: Session, token: str | None, settings: Settings, response: Response) -> dict:
    session = find_refresh_session(db, token)
    if not session:
        raise unauthorized()
    secret = new_secret()
    session.refresh_token_hash = hash_secret(secret)
    db.commit()
    set_refresh_cookie(response, f"{session.id}.{secret}", session, settings)
    return token_response(session, settings, response)
