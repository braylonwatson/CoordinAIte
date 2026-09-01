from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.dependencies import get_db, get_model_bundle
from game_tracker import ModelBundle


router = APIRouter(tags=["health"])


@router.get("/")
def root():
    return {"message": "CoordinAIte API is running"}


@router.get("/health/live")
def live():
    return {"status": "ok"}


@router.get("/health/ready")
def ready(
    db: Session = Depends(get_db),
    model_bundle: ModelBundle = Depends(get_model_bundle),
):
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database is unavailable") from exc
    if model_bundle.model is None:
        raise HTTPException(status_code=503, detail="Prediction model is unavailable")
    return {
        "status": "ready",
        "database": "ok",
        "tier1_model": "ok",
        "tier2_models": "ok" if model_bundle.tier2_available() else "unavailable",
    }
