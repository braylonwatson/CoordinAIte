import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from passlib.hash import pbkdf2_sha256

from app.core.config import Settings


def as_utc(value: datetime) -> datetime:
    # SQLite returns naive datetimes in tests; PostgreSQL preserves the timezone.
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def new_secret() -> str:
    return secrets.token_urlsafe(32)


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def create_access_token(user_id: int, session_id: str, session_expires_at: datetime, settings: Settings) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(user_id),
            "sid": session_id,
            "type": "access",
            "iat": now,
            "exp": min(now + timedelta(minutes=settings.access_token_minutes), as_utc(session_expires_at)),
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
        },
        settings.jwt_secret_key,
        algorithm="HS256",
    )


def decode_access_token(token: str, settings: Settings) -> dict:
    claims = jwt.decode(
        token,
        settings.jwt_secret_key,
        algorithms=["HS256"],
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
        options={"require": ["sub", "sid", "type", "iat", "exp", "iss", "aud"]},
    )
    if claims["type"] != "access" or not isinstance(claims["sid"], str) or not claims["sub"].isdigit():
        raise jwt.InvalidTokenError("Invalid access token claims")
    return claims


def hash_password(password: str) -> str:
    return pbkdf2_sha256.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    try:
        return pbkdf2_sha256.verify(password, hashed_password)
    except (ValueError, TypeError):
        return False
