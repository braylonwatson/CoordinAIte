from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
import stripe

from app.api.dependencies import get_db, get_model_bundle, get_settings
from app.core.config import Settings
from app.db.models import User
from app.schemas import CheckoutSessionRequest
from app.services.game_sessions import require_user
from app.services.subscriptions import (
    stripe_value,
    subscription_is_active,
    sync_user_subscription_fields,
    update_user_from_subscription_event,
)
from game_tracker import ModelBundle


router = APIRouter(tags=["billing"])


def configure_stripe(settings: Settings) -> None:
    stripe.api_key = settings.stripe_secret_key


def get_or_create_stripe_customer(
    db: Session,
    user: User,
    settings: Settings,
) -> str:
    configure_stripe(settings)
    if user.stripe_customer_id:
        return user.stripe_customer_id

    customer = stripe.Customer.create(
        email=user.email,
        name=user.username,
        metadata={"user_id": str(user.id)},
    )
    user.stripe_customer_id = customer.id
    db.commit()
    db.refresh(user)
    return user.stripe_customer_id


@router.get("/me/subscription")
def get_my_subscription(
    user_id: int,
    db: Session = Depends(get_db),
    model_bundle: ModelBundle = Depends(get_model_bundle),
):
    user = require_user(db, user_id)
    return {
        "user_id": user.id,
        "tier": user.tier or "free",
        "subscription_status": user.subscription_status,
        "tier2_access": subscription_is_active(user.subscription_status),
        "tier2_models_available": model_bundle.tier2_available(),
    }


@router.post("/create-checkout-session")
def create_checkout_session(
    data: CheckoutSessionRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    if not settings.stripe_secret_key:
        raise HTTPException(status_code=503, detail="Stripe is not configured.")
    if not settings.stripe_price_id_tier2:
        raise HTTPException(status_code=503, detail="Tier 2 price is not configured.")

    user = require_user(db, data.user_id)
    try:
        customer_id = get_or_create_stripe_customer(db, user, settings)
        checkout = stripe.checkout.Session.create(
            mode="subscription",
            customer=customer_id,
            client_reference_id=str(user.id),
            line_items=[
                {"price": settings.stripe_price_id_tier2, "quantity": 1}
            ],
            metadata={"user_id": str(user.id)},
            success_url=f"{settings.frontend_url}/?success=true",
            cancel_url=f"{settings.frontend_url}/?canceled=true",
        )
        return {"url": checkout.url}
    except stripe.StripeError as exc:
        raise HTTPException(status_code=502, detail="Stripe request failed") from exc


@router.post("/stripe/webhook")
async def stripe_webhook(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    if not settings.stripe_secret_key or not settings.stripe_webhook_secret:
        return JSONResponse(
            {"detail": "Stripe webhook verification is not configured."},
            status_code=503,
        )

    configure_stripe(settings)
    payload = await request.body()
    signature = request.headers.get("stripe-signature")
    if not signature:
        return JSONResponse({"detail": "Missing Stripe signature."}, status_code=400)

    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=signature,
            secret=settings.stripe_webhook_secret,
        )
    except ValueError:
        return JSONResponse({"detail": "Invalid webhook payload."}, status_code=400)
    except stripe.SignatureVerificationError:
        return JSONResponse({"detail": "Invalid webhook signature."}, status_code=400)

    event_type = stripe_value(event, "type")
    event_data = stripe_value(event, "data")
    event_obj = stripe_value(event_data, "object")

    if event_type == "checkout.session.completed":
        customer_id = stripe_value(event_obj, "customer")
        subscription_id = stripe_value(event_obj, "subscription")
        metadata = stripe_value(event_obj, "metadata", {}) or {}
        user_id = stripe_value(metadata, "user_id") or stripe_value(
            event_obj, "client_reference_id"
        )

        user = None
        if user_id:
            try:
                user = db.get(User, int(user_id))
            except (TypeError, ValueError):
                user = None
        if not user and customer_id:
            user = db.query(User).filter(User.stripe_customer_id == customer_id).first()

        if user:
            user.stripe_customer_id = customer_id or user.stripe_customer_id
            user.stripe_subscription_id = subscription_id
            status = "active"
            if subscription_id:
                try:
                    subscription = stripe.Subscription.retrieve(subscription_id)
                    status = stripe_value(subscription, "status", "active")
                except stripe.StripeError:
                    status = "active"
            sync_user_subscription_fields(user, status)
            db.commit()

    elif event_type in {
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
    }:
        update_user_from_subscription_event(db, event_obj)

    elif event_type in {"invoice.payment_failed", "invoice.payment_succeeded"}:
        customer_id = stripe_value(event_obj, "customer")
        user = None
        if customer_id:
            user = db.query(User).filter(User.stripe_customer_id == customer_id).first()
        if user:
            status = "past_due" if event_type == "invoice.payment_failed" else "active"
            subscription_id = stripe_value(event_obj, "subscription")
            if subscription_id:
                user.stripe_subscription_id = subscription_id
            sync_user_subscription_fields(user, status)
            db.commit()

    return JSONResponse({"status": "success"})
