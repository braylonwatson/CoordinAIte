from typing import Any

from sqlalchemy.orm import Session

from app.db.models import User


def subscription_is_active(status: str | None) -> bool:
    return status in {"active", "trialing"}


def sync_user_subscription_fields(user: User, status: str | None) -> None:
    user.subscription_status = status
    user.tier = "tier2" if subscription_is_active(status) else "free"


def stripe_value(obj: Any, key: str, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def update_user_from_subscription_event(db: Session, subscription_obj: Any) -> None:
    customer_id = stripe_value(subscription_obj, "customer")
    if not customer_id:
        return

    user = db.query(User).filter(User.stripe_customer_id == customer_id).first()
    if not user:
        return

    user.stripe_subscription_id = stripe_value(subscription_obj, "id")
    sync_user_subscription_fields(user, stripe_value(subscription_obj, "status"))
    db.commit()
