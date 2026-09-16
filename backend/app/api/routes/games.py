from copy import deepcopy

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, get_db, get_game_access, get_model_bundle
from app.db.models import SavedGame, User
from app.schemas import LoadGameRequest, SaveGameRequest
from app.services.game_sessions import (
    create_game_session,
    get_game_session,
    GameAccess,
)
from game_tracker import ModelBundle


router = APIRouter(tags=["saved games"])


@router.post("/games", status_code=201)
def save_game(
    data: SaveGameRequest,
    user: User = Depends(get_current_user),
    access: GameAccess = Depends(get_game_access),
    db: Session = Depends(get_db),
):
    snapshot = deepcopy(data.game_state)
    live_game = get_game_session(db, data.game_id, access, for_update=True)
    if live_game.user_id is None:
        # Claiming a guest game requires its private token, checked above.
        live_game.user_id = user.id
        live_game.guest_token_hash = None

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
        user_id=user.id,
        title=data.title.strip(),
        game_state=snapshot,
    )
    db.add(game)
    db.commit()
    db.refresh(game)
    return {"game_id": game.id}


@router.get("/games")
def get_games(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    games = (
        db.query(SavedGame)
        .filter(SavedGame.user_id == user.id)
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
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    model_bundle: ModelBundle = Depends(get_model_bundle),
):
    saved_game = (
        db.query(SavedGame)
        .filter(
            SavedGame.id == data.game_id,
            SavedGame.user_id == user.id,
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
        user_id=user.id,
        tracker_state=tracker_state,
    )
    return {
        "message": "Game loaded",
        "state": state,
        "game_id": live_game.id,
        "state_version": live_game.version,
    }


@router.delete("/games/{game_id}")
def delete_game(game_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    game = (
        db.query(SavedGame)
        .filter(SavedGame.id == game_id, SavedGame.user_id == user.id)
        .first()
    )
    if not game:
        raise HTTPException(status_code=404, detail="Saved game not found")
    db.delete(game)
    db.commit()
    return {"message": "Game deleted"}
