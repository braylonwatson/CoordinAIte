from copy import deepcopy

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.dependencies import get_db, get_model_bundle
from app.db.models import SavedGame
from app.schemas import LoadGameRequest, SaveGameRequest
from app.services.game_sessions import (
    create_game_session,
    get_game_session,
    require_user,
)
from game_tracker import ModelBundle


router = APIRouter(tags=["saved games"])


@router.post("/games", status_code=201)
def save_game(
    data: SaveGameRequest,
    db: Session = Depends(get_db),
):
    require_user(db, data.user_id)
    snapshot = deepcopy(data.game_state)

    if data.game_id:
        live_game = get_game_session(db, data.game_id)
        if live_game.user_id not in {None, data.user_id}:
            raise HTTPException(status_code=403, detail="Game does not belong to this user")
        if live_game.user_id is None:
            live_game.user_id = data.user_id

        tracker_state = deepcopy(live_game.tracker_state)
        snapshot.update(
            {
                "offense": live_game.offense,
                "defense": live_game.defense,
                "play_log": tracker_state.get("play_log", []),
                "pending": tracker_state.get("pending_play_context") or {},
                "current_drive_number": tracker_state.get("current_drive_number", 1),
                "tracker_state": tracker_state,
            }
        )

    game = SavedGame(
        user_id=data.user_id,
        title=data.title.strip(),
        game_state=snapshot,
    )
    db.add(game)
    db.commit()
    db.refresh(game)
    return {"game_id": game.id}


@router.get("/games/{user_id}")
def get_games(user_id: int, db: Session = Depends(get_db)):
    require_user(db, user_id)
    games = (
        db.query(SavedGame)
        .filter(SavedGame.user_id == user_id)
        .order_by(SavedGame.id.desc())
        .all()
    )
    return [
        {
            "id": game.id,
            "user_id": game.user_id,
            "title": game.title,
            "game_state": game.game_state,
        }
        for game in games
    ]


@router.post("/games/load")
def load_game(
    data: LoadGameRequest,
    db: Session = Depends(get_db),
    model_bundle: ModelBundle = Depends(get_model_bundle),
):
    saved_game = (
        db.query(SavedGame)
        .filter(
            SavedGame.id == data.game_id,
            SavedGame.user_id == data.user_id,
        )
        .first()
    )
    if not saved_game:
        raise HTTPException(status_code=404, detail="Saved game not found")

    state = deepcopy(saved_game.game_state)
    tracker_state = state.get("tracker_state") or {
        "offense": state.get("offense"),
        "defense": state.get("defense"),
        "play_log": state.get("play_log", []),
        "pending_play_context": state.get("pending") or None,
        "current_drive_number": state.get("current_drive_number", 1),
    }
    live_game = create_game_session(
        db=db,
        model_bundle=model_bundle,
        offense=state.get("offense"),
        defense=state.get("defense"),
        user_id=data.user_id,
        tracker_state=tracker_state,
    )
    return {
        "message": "Game loaded",
        "state": state,
        "game_id": live_game.id,
        "state_version": live_game.version,
    }


@router.delete("/games/{game_id}")
def delete_game(game_id: int, user_id: int, db: Session = Depends(get_db)):
    game = (
        db.query(SavedGame)
        .filter(SavedGame.id == game_id, SavedGame.user_id == user_id)
        .first()
    )
    if not game:
        raise HTTPException(status_code=404, detail="Saved game not found")
    db.delete(game)
    db.commit()
    return {"message": "Game deleted"}
