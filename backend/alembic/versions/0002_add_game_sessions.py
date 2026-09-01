"""Add durable live-game sessions for stateless API containers."""

from alembic import op
import sqlalchemy as sa


revision = "0002_game_sessions"
down_revision = "0001_legacy_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_saved_games_user_id", "saved_games", ["user_id"])
    op.create_table(
        "game_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("offense", sa.String(length=3), nullable=False),
        sa.Column("defense", sa.String(length=3), nullable=False),
        sa.Column("tracker_state", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_game_sessions_user_id_users",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_game_sessions"),
    )
    op.create_index("ix_game_sessions_user_id", "game_sessions", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_game_sessions_user_id", table_name="game_sessions")
    op.drop_table("game_sessions")
    op.drop_index("ix_saved_games_user_id", table_name="saved_games")
