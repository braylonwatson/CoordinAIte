"""Create the legacy user and saved-game schema for fresh databases.

Existing CoordinAIte databases should be stamped at this revision before
running the next migration.
"""

from alembic import op
import sqlalchemy as sa


revision = "0001_legacy_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("tier", sa.String(), nullable=False, server_default="free"),
        sa.Column("subscription_status", sa.String(), nullable=True),
        sa.Column("stripe_customer_id", sa.String(), nullable=True),
        sa.Column("stripe_subscription_id", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("ix_users_id", "users", ["id"])
    op.create_table(
        "saved_games",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("game_state", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_saved_games_user_id_users",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_saved_games"),
    )
    op.create_index("ix_saved_games_id", "saved_games", ["id"])


def downgrade() -> None:
    op.drop_index("ix_saved_games_id", table_name="saved_games")
    op.drop_table("saved_games")
    op.drop_index("ix_users_id", table_name="users")
    op.drop_table("users")
