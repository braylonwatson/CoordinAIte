from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import GameSession, User
from game_tracker import GameTracker, ModelBundle


VALID_TEAMS = {
    "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE",
    "DAL", "DEN", "DET", "GB", "HOU", "IND", "JAX", "KC",
    "LAC", "LAR", "LV", "MIA", "MIN", "NE", "NO", "NYG",
    "NYJ", "PHI", "PIT", "SEA", "SF", "TB", "TEN", "WAS",
}


def normalize_team(team: str | None) -> str:
    return (team or "").strip().upper()


def validate_team_code(team: str, field_name: str) -> None:
    if team not in VALID_TEAMS:
        raise HTTPException(
            status_code=400,
            detail=f"{field_name} must be a valid NFL team abbreviation.",
        )


def require_user(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


def create_game_session(
    db: Session,
    model_bundle: ModelBundle,
    offense: str,
    defense: str,
    user_id: int | None = None,
    tracker_state: dict | None = None,
) -> GameSession:
    offense = normalize_team(offense)
    defense = normalize_team(defense)
    validate_team_code(offense, "Offense")
    validate_team_code(defense, "Defense")

    if user_id is not None:
        require_user(db, user_id)

    tracker = GameTracker(model_bundle=model_bundle, state=tracker_state)
    tracker.set_teams(offense, defense)
    game = GameSession(
        id=str(uuid4()),
        user_id=user_id,
        offense=offense,
        defense=defense,
        tracker_state=tracker.export_state(),
        version=1,
        status="active",
    )
    db.add(game)
    db.commit()
    db.refresh(game)
    return game


def get_game_session(
    db: Session,
    game_id: str,
    *,
    for_update: bool = False,
) -> GameSession:
    statement = select(GameSession).where(GameSession.id == game_id)
    if for_update:
        statement = statement.with_for_update()
    game = db.execute(statement).scalar_one_or_none()
    if not game:
        raise HTTPException(status_code=404, detail="Game session not found")
    return game


def build_tracker(game: GameSession, model_bundle: ModelBundle) -> GameTracker:
    return GameTracker(model_bundle=model_bundle, state=game.tracker_state)


def persist_tracker(game: GameSession, tracker: GameTracker) -> None:
    game.offense = tracker.offense
    game.defense = tracker.defense
    game.tracker_state = tracker.export_state()
    game.version += 1
