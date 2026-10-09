"""Versioned, private game snapshots. PostgreSQL authorizes every read."""
import json
import logging
from types import SimpleNamespace

from fastapi import HTTPException
from redis.exceptions import RedisError
from sqlalchemy import and_, false, or_, select
from sqlalchemy.orm import Session

from app.core.security import hash_secret
from app.db.models import GameSession
from app.services.game_sessions import GameAccess, build_tracker, get_game_session
from game_tracker import ModelBundle


logger = logging.getLogger(__name__)
SNAPSHOT_TTL_SECONDS = 300


def read_game_tracker(db: Session, game_id: str, access: GameAccess, models: ModelBundle, cache):
    """Authorize and check the DB version before considering a cached snapshot.

    Never put credentials, ownership, or entitlements in Redis. Mutating routes
    continue to lock and read the PostgreSQL row directly.
    """
    owned = GameSession.user_id == access.user.id if access.user else false()
    guest = (
        and_(GameSession.user_id.is_(None), GameSession.guest_token_hash == hash_secret(access.guest_token))
        if access.guest_token else false()
    )
    row = db.execute(
        select(GameSession.id, GameSession.version)
        .where(GameSession.id == game_id, or_(owned, guest))
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Game session not found")

    key = f"coordinaite:game:v1:{row.id}:{row.version}"
    if cache is not None:
        try:
            snapshot = cache.get(key)
            if snapshot is not None:
                state = json.loads(snapshot)
                if not isinstance(state, dict):
                    raise ValueError("Invalid game snapshot")
                return SimpleNamespace(id=row.id, version=row.version), build_tracker(
                    SimpleNamespace(tracker_state=state), models
                )
        except (RedisError, ValueError, TypeError):
            logger.warning("Game snapshot cache unavailable; reading PostgreSQL", exc_info=True)

    game = get_game_session(db, game_id, access)
    tracker = build_tracker(game, models)
    if cache is not None:
        try:
            cache.setex(
                f"coordinaite:game:v1:{game.id}:{game.version}",
                SNAPSHOT_TTL_SECONDS,
                json.dumps(game.tracker_state),
            )
        except (RedisError, ValueError, TypeError):
            logger.warning("Could not populate game snapshot cache", exc_info=True)
    return game, tracker
