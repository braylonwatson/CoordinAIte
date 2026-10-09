"""Record user/subscription timestamps and persist refund requests."""

from alembic import op
import sqlalchemy as sa


revision = "0004_user_timestamps_refunds"
down_revision = "0003_auth_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Keep existing rows NULL: the original signup/login/subscription dates were
    # not recorded, and a migration date must not be presented as real history.
    for name in (
        "created_at",
        "updated_at",
        "subscription_started_at",
        "subscription_ended_at",
        "subscription_status_changed_at",
        "last_login_at",
    ):
        op.add_column("users", sa.Column(name, sa.DateTime(timezone=True), nullable=True))

    # Defaults apply to future inserts, not to legacy accounts already in users.
    with op.batch_alter_table("users") as batch:
        batch.alter_column("created_at", server_default=sa.func.now())
        batch.alter_column("updated_at", server_default=sa.func.now())
    op.create_index("ix_users_created_at", "users", ["created_at"])

    op.create_table(
        "refund_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by_user_id", sa.Integer(), nullable=True),
        sa.Column("stripe_customer_id", sa.String(), nullable=True),
        sa.Column("stripe_subscription_id", sa.String(), nullable=True),
        sa.Column("stripe_refund_id", sa.String(), nullable=True),
        sa.Column("stripe_refund_status", sa.String(length=24), nullable=True),
        sa.Column("stripe_payment_intent_id", sa.String(), nullable=True),
        sa.Column("refund_amount_cents", sa.Integer(), nullable=True),
        sa.Column("refund_currency", sa.String(length=3), nullable=True),
        sa.Column("resolution_message", sa.String(length=500), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_refund_requests_user_id_users"),
        sa.ForeignKeyConstraint(
            ["reviewed_by_user_id"], ["users.id"], name="fk_refund_requests_reviewer_id_users"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_refund_requests"),
    )
    op.create_index("ix_refund_requests_user_id", "refund_requests", ["user_id"])
    op.create_index("ix_refund_requests_status", "refund_requests", ["status"])
    op.create_index("ix_refund_requests_created_at", "refund_requests", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_refund_requests_created_at", table_name="refund_requests")
    op.drop_index("ix_refund_requests_status", table_name="refund_requests")
    op.drop_index("ix_refund_requests_user_id", table_name="refund_requests")
    op.drop_table("refund_requests")
    op.drop_index("ix_users_created_at", table_name="users")
    with op.batch_alter_table("users") as batch:
        batch.alter_column("created_at", server_default=None)
        batch.alter_column("updated_at", server_default=None)
    for name in (
        "last_login_at",
        "subscription_status_changed_at",
        "subscription_ended_at",
        "subscription_started_at",
        "updated_at",
        "created_at",
    ):
        op.drop_column("users", name)
