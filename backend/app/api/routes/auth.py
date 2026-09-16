import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, get_db, get_settings, require_cookie_request
from app.core.config import Settings
from app.core.security import decode_access_token, hash_password, verify_password
from app.db.models import AuthSession, User, utc_now
from app.schemas import LoginRequest, SignupRequest
from app.services.auth_sessions import (
    REFRESH_COOKIE, begin_session, clear_refresh_cookie, find_refresh_session,
    refresh_session, user_response,
)


router = APIRouter(tags=["authentication"])


def normalize_email(email: str | None) -> str:
    return (email or "").strip().lower()


@router.post("/signup", status_code=201, dependencies=[Depends(require_cookie_request)])
def signup(
    data: SignupRequest,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    email = normalize_email(data.email)
    existing = db.query(User).filter(User.email == email).first()
    if existing:
        raise HTTPException(status_code=409, detail="User already exists")

    user = User(
        username=data.username.strip(),
        email=email,
        password_hash=hash_password(data.password),
        tier="free",
        subscription_status=None,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="User already exists")
    db.refresh(user)

    return begin_session(db, user, settings, response)


@router.post("/login", dependencies=[Depends(require_cookie_request)])
def login(
    data: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    email = normalize_email(data.email)
    user = db.query(User).filter(User.email == email).first()
    # Verify a fixed dummy hash too, avoiding a fast path for nonexistent emails.
    valid = verify_password(data.password, user.password_hash if user else DUMMY_PASSWORD_HASH)
    if not user or not valid:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    return begin_session(db, user, settings, response)


DUMMY_PASSWORD_HASH = hash_password("not-a-real-account-password")


@router.get("/me")
def me(response: Response, user: User = Depends(get_current_user)):
    response.headers["Cache-Control"] = "no-store"
    return user_response(user)


@router.post("/auth/refresh", dependencies=[Depends(require_cookie_request)])
def refresh(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    return refresh_session(db, request.cookies.get(REFRESH_COOKIE), settings, response)


@router.post("/auth/logout", status_code=204, dependencies=[Depends(require_cookie_request)])
def logout(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    # Revoke the presented cookie and/or valid bearer session. Logout remains
    # idempotent when a token has expired or a cookie was already removed.
    sessions = []
    authorization = request.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() == "bearer":
        try:
            claims = decode_access_token(token, settings)
            session = db.get(AuthSession, claims["sid"])
            if session and str(session.user_id) == claims["sub"]:
                sessions.append(session)
        except jwt.InvalidTokenError:
            pass
    cookie_session = find_refresh_session(db, request.cookies.get(REFRESH_COOKIE))
    if cookie_session:
        sessions.append(cookie_session)
    for session in sessions:
        session.revoked_at = utc_now()
    db.commit()
    response = Response(status_code=204, headers={"Cache-Control": "no-store"})
    clear_refresh_cookie(response, settings)
    return response
