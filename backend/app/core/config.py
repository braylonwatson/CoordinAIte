import os
from dataclasses import dataclass
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
        )
