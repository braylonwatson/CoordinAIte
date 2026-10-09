from time import perf_counter

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis import Redis

from app.api.router import api_router
from app.core.config import Settings
from app.db.base import Base
from app.db.session import build_engine, build_session_factory
from game_tracker import ModelBundle


def create_app(
    settings: Settings | None = None,
    model_bundle: ModelBundle | None = None,
    *,
    create_tables: bool = False,
) -> FastAPI:
    settings = settings or Settings.from_environment()
    settings.validate_auth()
    engine = build_engine(settings.database_url)

    # Production uses Alembic. This option exists only for isolated tests.
    if create_tables:
        Base.metadata.create_all(bind=engine)

    application = FastAPI(
        title="CoordinAIte API",
        version="1.0.0",
        docs_url="/docs" if settings.app_environment != "production" else None,
        redoc_url="/redoc" if settings.app_environment != "production" else None,
    )
    application.state.settings = settings
    application.state.engine = engine
    application.state.session_factory = build_session_factory(engine)
    application.state.model_bundle = model_bundle or ModelBundle.load()
    application.state.game_cache = (
        Redis.from_url(settings.redis_url, socket_connect_timeout=0.15, socket_timeout=0.15,
                       retry_on_timeout=False)
        if settings.redis_url else None
    )

    @application.middleware("http")
    async def prevent_account_response_caching(request, call_next):
        started = perf_counter()
        response = await call_next(request)
        # Game responses can contain private account or guest state.
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers["Server-Timing"] = f"app;dur={(perf_counter() - started) * 1000:.3f}"
        return response

    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Game-Token", "X-CSRF-Protection"],
        expose_headers=["Server-Timing"],
    )
    application.include_router(api_router)
    return application
