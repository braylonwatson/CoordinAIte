from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.orm import relationship

from app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    tier = Column(String, nullable=False, default="free")
    subscription_status = Column(String, nullable=True)
    stripe_customer_id = Column(String, nullable=True)
    stripe_subscription_id = Column(String, nullable=True)
    # Timestamp history is nullable for legacy accounts whose original dates
    # were never recorded. New accounts receive database-generated timestamps.
    created_at = Column(DateTime(timezone=True), nullable=True, default=utc_now, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), nullable=True, default=utc_now,
        onupdate=utc_now, server_default=func.now(),
    )
    subscription_started_at = Column(DateTime(timezone=True), nullable=True)
    subscription_ended_at = Column(DateTime(timezone=True), nullable=True)
    subscription_status_changed_at = Column(DateTime(timezone=True), nullable=True)
    last_login_at = Column(DateTime(timezone=True), nullable=True)


class SavedGame(Base):
    __tablename__ = "saved_games"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String, nullable=False)
    game_state = Column(JSON, nullable=False)

    user = relationship("User")


class AuthSession(Base):
    """Shared login state permits refresh rotation and immediate logout on any worker."""

    __tablename__ = "auth_sessions"

    id = Column(String(36), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    refresh_token_hash = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User")


class RefundRequest(Base):
    """A customer refund request awaiting an owner's decision."""

    __tablename__ = "refund_requests"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    reason = Column(Text, nullable=False)
    status = Column(String(24), nullable=False, default="pending", server_default="pending", index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now())
    notified_at = Column(DateTime(timezone=True), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    reviewed_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    # Snapshot the billing target so a later subscription cannot be refunded
    # accidentally if the request is reviewed after the account changes plans.
    stripe_customer_id = Column(String, nullable=True)
    stripe_subscription_id = Column(String, nullable=True)
    stripe_refund_id = Column(String, nullable=True)
    stripe_refund_status = Column(String(24), nullable=True)
    stripe_payment_intent_id = Column(String, nullable=True)
    refund_amount_cents = Column(Integer, nullable=True)
    refund_currency = Column(String(3), nullable=True)
    resolution_message = Column(String(500), nullable=True)
    user = relationship("User", foreign_keys=[user_id])
    reviewer = relationship("User", foreign_keys=[reviewed_by_user_id])


class GameSession(Base):
    """Durable live-game state shared by every API container."""

    __tablename__ = "game_sessions"

    id = Column(String(36), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    guest_token_hash = Column(String(64), nullable=True)
    offense = Column(String(3), nullable=False)
    defense = Column(String(3), nullable=False)
    tracker_state = Column(JSON, nullable=False)
    version = Column(Integer, nullable=False, default=1)
    status = Column(String(20), nullable=False, default="active")
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    user = relationship("User")
