"""Add revocable login sessions and private guest game access."""

from alembic import op
import sqlalchemy as sa


revision = "0003_auth_sessions"
down_revision = "0002_game_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("refresh_token_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    # Existing registered-user ownership and saved games are preserved.
    # Old anonymous sessions have no secret, so they deliberately remain inaccessible.
    op.add_column("game_sessions", sa.Column("guest_token_hash", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("game_sessions", "guest_token_hash")
    op.drop_index("ix_auth_sessions_user_id", table_name="auth_sessions")
    op.drop_table("auth_sessions")
