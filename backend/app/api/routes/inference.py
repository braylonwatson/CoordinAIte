from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.dependencies import get_db, get_model_bundle
from app.schemas import GameActionRequest, LogPlayRequest, PredictRequest, TeamRequest
from app.services.game_sessions import (
    build_tracker,
    create_game_session,
    get_game_session,
    persist_tracker,
    require_user,
)
from app.services.subscriptions import subscription_is_active
from game_tracker import ModelBundle


router = APIRouter(tags=["live game inference"])


def state_response(game, tracker) -> dict:
    return {
        "game_id": game.id,
        "state_version": game.version,
        "offense": tracker.offense,
        "defense": tracker.defense,
        "prev_play_pass": tracker.prev_play_pass,
        "game_total_plays": tracker.game_total_plays,
        "game_total_passes": tracker.game_total_passes,
        "current_drive_number": tracker.current_drive_number,
        "drive_total_plays": tracker.drive_total_plays,
        "drive_total_passes": tracker.drive_total_passes,
        "tier2_available": tracker.tier2_available(),
    }


@router.get("/tier2-status")
def tier2_status(model_bundle: ModelBundle = Depends(get_model_bundle)):
    return {"tier2_available": model_bundle.tier2_available()}


@router.post("/set-teams", status_code=201)
def set_teams(
    data: TeamRequest,
    db: Session = Depends(get_db),
    model_bundle: ModelBundle = Depends(get_model_bundle),
):
    game = create_game_session(
        db=db,
        model_bundle=model_bundle,
        offense=data.offense,
        defense=data.defense,
        user_id=data.user_id,
    )
    return {
        "message": "Game session created",
        "game_id": game.id,
        "state_version": game.version,
        "offense": game.offense,
        "defense": game.defense,
    }


@router.get("/state")
def get_state(
    game_id: str = Query(min_length=36, max_length=36),
    db: Session = Depends(get_db),
    model_bundle: ModelBundle = Depends(get_model_bundle),
):
    game = get_game_session(db, game_id)
    tracker = build_tracker(game, model_bundle)
    return state_response(game, tracker)


def make_prediction(
    data: PredictRequest,
    *,
    tier: int,
    db: Session,
    model_bundle: ModelBundle,
):
    game = get_game_session(db, data.game_id, for_update=True)
    if tier == 2:
        if not data.user_id:
            raise HTTPException(
                status_code=403,
                detail="Tier 2 prediction requires a logged-in Tier 2 account.",
            )
        user = require_user(db, data.user_id)
        if game.user_id not in {None, user.id}:
            raise HTTPException(status_code=403, detail="Game does not belong to this user")
        if not subscription_is_active(user.subscription_status):
            raise HTTPException(status_code=403, detail="Tier 2 subscription required")

    tracker = build_tracker(game, model_bundle)
    try:
        prediction_method = (
            tracker.predict_next_play_tier2 if tier == 2 else tracker.predict_next_play
        )
        result = prediction_method(
            down=data.down,
            ydstogo=data.ydstogo,
            yardline_100=data.yardline_100,
            game_seconds_remaining=data.game_seconds_remaining,
            qtr=data.qtr,
            score_differential=data.score_differential,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    persist_tracker(game, tracker)
    db.commit()
    result.update({"game_id": game.id, "state_version": game.version})
    return result


@router.post("/predict")
def predict(
    data: PredictRequest,
    db: Session = Depends(get_db),
    model_bundle: ModelBundle = Depends(get_model_bundle),
):
    return make_prediction(data, tier=1, db=db, model_bundle=model_bundle)


@router.post("/predict-tier2")
def predict_tier2(
    data: PredictRequest,
    db: Session = Depends(get_db),
    model_bundle: ModelBundle = Depends(get_model_bundle),
):
    return make_prediction(data, tier=2, db=db, model_bundle=model_bundle)


@router.get("/pending")
def get_pending(
    game_id: str = Query(min_length=36, max_length=36),
    db: Session = Depends(get_db),
    model_bundle: ModelBundle = Depends(get_model_bundle),
):
    game = get_game_session(db, game_id)
    tracker = build_tracker(game, model_bundle)
    return tracker.pending_play_context or {}


@router.post("/log-play")
def log_play(
    data: LogPlayRequest,
    db: Session = Depends(get_db),
    model_bundle: ModelBundle = Depends(get_model_bundle),
):
    game = get_game_session(db, data.game_id, for_update=True)
    tracker = build_tracker(game, model_bundle)
    try:
        tracker.log_pending_result(
            actual_play_type=data.actual_play_type,
            yards_gained=data.yards_gained,
            epa=data.epa,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    persist_tracker(game, tracker)
    db.commit()
    return {
        "message": "Play logged successfully",
        "game_id": game.id,
        "state_version": game.version,
    }


@router.get("/play-log")
def get_play_log(
    game_id: str = Query(min_length=36, max_length=36),
    db: Session = Depends(get_db),
    model_bundle: ModelBundle = Depends(get_model_bundle),
):
    game = get_game_session(db, game_id)
    tracker = build_tracker(game, model_bundle)
    return tracker.play_log


@router.post("/new-drive")
def new_drive(
    data: GameActionRequest,
    db: Session = Depends(get_db),
    model_bundle: ModelBundle = Depends(get_model_bundle),
):
    game = get_game_session(db, data.game_id, for_update=True)
    tracker = build_tracker(game, model_bundle)
    tracker.start_new_drive()
    persist_tracker(game, tracker)
    db.commit()
    return {
        "message": "New drive started",
        "drive_number": tracker.current_drive_number,
        "game_id": game.id,
        "state_version": game.version,
    }


@router.get("/summary")
def get_summary(
    game_id: str = Query(min_length=36, max_length=36),
    db: Session = Depends(get_db),
    model_bundle: ModelBundle = Depends(get_model_bundle),
):
    game = get_game_session(db, game_id)
    tracker = build_tracker(game, model_bundle)
    return tracker.summary()
