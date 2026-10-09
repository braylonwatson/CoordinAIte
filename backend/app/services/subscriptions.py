from datetime import datetime, timezone
from typing import Any

from app.db.models import User


def subscription_is_active(status: str | None) -> bool:
    return status in {"active", "trialing"}


def stripe_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def sync_user_subscription_fields(
    user: User,
    status: str | None,
    subscription: Any = None,
    *,
    subscription_id_changed: bool = False,
) -> None:
    from app.db.models import utc_now

    previous_status = user.subscription_status
    user.subscription_status = status
    user.tier = "tier2" if subscription_is_active(status) else "free"
    if previous_status != status:
        user.subscription_status_changed_at = utc_now()

    if subscription_id_changed:
        user.subscription_started_at = None
        user.subscription_ended_at = None
    if subscription_is_active(status):
        if user.subscription_started_at is None:
            user.subscription_started_at = (
                stripe_timestamp(stripe_value(subscription, "start_date"))
                or stripe_timestamp(stripe_value(subscription, "created"))
                or utc_now()
            )
        user.subscription_ended_at = None
    elif status in {"canceled", "unpaid", "incomplete_expired"}:
        user.subscription_ended_at = (
            stripe_timestamp(stripe_value(subscription, "ended_at"))
            or stripe_timestamp(stripe_value(subscription, "canceled_at"))
            or user.subscription_ended_at
            or utc_now()
        )


def stripe_value(obj: Any, key: str, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def stripe_id(value: Any) -> str | None:
    return value if isinstance(value, str) else stripe_value(value, "id")


def is_tier2_price(price: Any) -> bool:
    recurring = stripe_value(price, "recurring")
    return (
        stripe_value(price, "active") is True
        and stripe_value(price, "currency") == "usd"
        and stripe_value(price, "unit_amount") == 1000
        and stripe_value(price, "billing_scheme") == "per_unit"
        and not stripe_value(price, "transform_quantity")
        and stripe_value(recurring, "interval") == "month"
        and stripe_value(recurring, "interval_count") == 1
        and stripe_value(recurring, "usage_type") == "licensed"
    )


def subscription_has_product(subscription: Any, product_id: str) -> bool:
    items = stripe_value(stripe_value(subscription, "items"), "data", [])
    return any(
        stripe_id(stripe_value(stripe_value(item, "price"), "product")) == product_id
        for item in items
    )
