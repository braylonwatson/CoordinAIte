from fastapi import APIRouter

from app.api.routes import auth, billing, games, health, inference, realtime


api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(billing.router)
api_router.include_router(games.router)
api_router.include_router(inference.router)
api_router.include_router(realtime.router)
