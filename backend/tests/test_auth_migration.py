from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from app.db.session import build_engine


@pytest.mark.parametrize("existing_phase_one", [False, True])
def test_auth_migration_on_fresh_and_existing_database(tmp_path, monkeypatch, existing_phase_one):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'migration.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    engine = build_engine(database_url)
    if existing_phase_one:
        command.upgrade(config, "0002_game_sessions")
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO users (id, username, email, password_hash, tier) VALUES (1, 'Coach', 'coach@example.com', 'existing-hash', 'free')"))
            connection.execute(text("INSERT INTO saved_games (id, user_id, title, game_state) VALUES (1, 1, 'Keep this game', '{}')"))
            connection.execute(text("INSERT INTO game_sessions (id, user_id, offense, defense, tracker_state) VALUES ('00000000-0000-0000-0000-000000000001', 1, 'KC', 'BUF', '{}')"))
    command.upgrade(config, "head")
    inspector = inspect(engine)
    assert "auth_sessions" in inspector.get_table_names()
    assert "guest_token_hash" in {column["name"] for column in inspector.get_columns("game_sessions")}
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0003_auth_sessions"
        if existing_phase_one:
            assert connection.scalar(text("SELECT title FROM saved_games WHERE id = 1")) == "Keep this game"
            assert connection.scalar(text("SELECT user_id FROM game_sessions")) == 1
            assert connection.scalar(text("SELECT password_hash FROM users")) == "existing-hash"
    command.downgrade(config, "0002_game_sessions")
    assert "auth_sessions" not in inspect(engine).get_table_names()
    if existing_phase_one:
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT title FROM saved_games WHERE id = 1")) == "Keep this game"
