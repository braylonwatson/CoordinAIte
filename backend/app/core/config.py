import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def normalize_database_url(url: str) -> str:
    # Older Render connection strings can use postgres://, which SQLAlchemy
    # no longer accepts as a dialect name.
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql://", 1)
    return url


@dataclass(frozen=True)
class Settings:
    database_url: str
    frontend_url: str = "http://localhost:3000"
    cors_origins: tuple[str, ...] = ("http://localhost:3000",)
    stripe_secret_key: str | None = None
    stripe_price_id_tier2: str | None = None
    stripe_webhook_secret: str | None = None
    app_environment: str = "development"
    jwt_secret_key: str = field(default="", repr=False)
    jwt_issuer: str = "coordinaite"
    jwt_audience: str = "coordinaite-api"
    access_token_minutes: int = 15
    refresh_token_days: int = 7
    auth_cookie_secure: bool = False
    auth_cookie_samesite: str = "lax"

    def validate_auth(self) -> None:
        if len(self.jwt_secret_key.encode("utf-8")) < 32:
            raise RuntimeError("JWT_SECRET_KEY must contain at least 32 bytes. Generate a random secret.")
        if not 1 <= self.access_token_minutes <= 60:
            raise RuntimeError("ACCESS_TOKEN_MINUTES must be between 1 and 60.")
        if not 1 <= self.refresh_token_days <= 30:
            raise RuntimeError("REFRESH_TOKEN_DAYS must be between 1 and 30.")
        if self.auth_cookie_samesite not in {"lax", "strict", "none"}:
            raise RuntimeError("AUTH_COOKIE_SAMESITE must be lax, strict, or none.")
        if (self.app_environment == "production" or self.auth_cookie_samesite == "none") and not self.auth_cookie_secure:
            raise RuntimeError("Production and SameSite=None require AUTH_COOKIE_SECURE=true.")
        if not self.cors_origins or "*" in self.cors_origins:
            raise RuntimeError("CORS_ORIGINS must list explicit frontend origins.")

    @classmethod
    def from_environment(cls) -> "Settings":
        load_dotenv(PROJECT_ROOT / ".env", override=False)
        raw_database_url = os.getenv("DATABASE_URL")
        if not raw_database_url:
            raise RuntimeError("DATABASE_URL is not set.")

        frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000").rstrip("/")
        raw_origins = os.getenv("CORS_ORIGINS", frontend_url)
        cors_origins = tuple(
            origin.strip().rstrip("/")
            for origin in raw_origins.split(",")
            if origin.strip()
        )

        return cls(
            database_url=normalize_database_url(raw_database_url),
            frontend_url=frontend_url,
            cors_origins=cors_origins,
            stripe_secret_key=os.getenv("STRIPE_SECRET_KEY"),
            stripe_price_id_tier2=os.getenv("STRIPE_PRICE_ID_TIER2"),
            stripe_webhook_secret=os.getenv("STRIPE_WEBHOOK_SECRET"),
            app_environment=os.getenv("APP_ENV", "development"),
            jwt_secret_key=os.getenv("JWT_SECRET_KEY", ""),
            jwt_issuer=os.getenv("JWT_ISSUER", "coordinaite"),
            jwt_audience=os.getenv("JWT_AUDIENCE", "coordinaite-api"),
            access_token_minutes=int(os.getenv("ACCESS_TOKEN_MINUTES", "15")),
            refresh_token_days=int(os.getenv("REFRESH_TOKEN_DAYS", "7")),
            auth_cookie_secure=os.getenv(
                "AUTH_COOKIE_SECURE", "true" if os.getenv("APP_ENV") == "production" else "false"
            ).lower() == "true",
            auth_cookie_samesite=os.getenv("AUTH_COOKIE_SAMESITE", "lax").lower(),
        )
