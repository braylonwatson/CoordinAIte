import hashlib

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
import stripe

from app.api.dependencies import get_current_user, get_db, get_model_bundle, get_settings
from app.core.config import Settings
from app.db.models import User
from app.schemas import CheckoutSessionRequest
from app.services.subscriptions import (
    is_tier2_price,
    stripe_id,
    stripe_value,
    subscription_has_product,
    subscription_is_active,
    sync_user_subscription_fields,
)
from game_tracker import ModelBundle


router = APIRouter(tags=["billing"])
SUBSCRIPTION_EVENTS = {
    "checkout.session.completed",
    "customer.subscription.created",
    "customer.subscription.updated",
    "customer.subscription.deleted",
    "invoice.payment_failed",
    "invoice.payment_succeeded",
    "charge.refunded",
}
ENDED_STATUSES = {"canceled", "incomplete_expired"}


def locked_user(db: Session, user_id: int) -> User:
    # Serialize checkout and webhook reconciliation across API workers.
    return db.query(User).filter(User.id == user_id).populate_existing().with_for_update().one()


def get_or_create_stripe_customer(db: Session, user: User, settings: Settings) -> str:
    if not user.stripe_customer_id:
        # Scope retries to this installation; a reset DB must not reuse old customers.
        identity = f"{settings.jwt_secret_key}:{user.id}:{user.email}"
        token = hashlib.sha256(identity.encode()).hexdigest()
        customer = stripe.Customer.create(
            email=user.email, name=user.username,
            metadata={"user_id": str(user.id), "app": "coordinaite"},
            idempotency_key=f"coordinaite-customer-{token}",
            api_key=settings.stripe_secret_key,
        )
        user.stripe_customer_id = customer.id
        db.flush()
    return user.stripe_customer_id


def reconcile_subscription(user: User, settings: Settings, price=None) -> None:
    """Assign current Stripe state; repeated or delayed events are safe to replay."""
    price = price or stripe.Price.retrieve(
        settings.stripe_price_id_tier2, api_key=settings.stripe_secret_key,
    )
    product_id = stripe_id(stripe_value(price, "product"))
    subscriptions = stripe.Subscription.list(
        customer=user.stripe_customer_id, status="all", limit=100,
        api_key=settings.stripe_secret_key,
    )
    relevant = [
        sub for sub in subscriptions.auto_paging_iter()
        if product_id and subscription_has_product(sub, product_id)
    ]
    # An older canceled subscription must not revoke a newer active one.
    current = max(relevant, key=lambda sub: (
        subscription_is_active(stripe_value(sub, "status")),
        stripe_value(sub, "status") not in ENDED_STATUSES,
        stripe_value(sub, "created", 0),
        stripe_value(sub, "id", ""),
    ), default=None)
    current_id = stripe_id(current)
    subscription_id_changed = bool(current_id and current_id != user.stripe_subscription_id)
    user.stripe_subscription_id = current_id
    sync_user_subscription_fields(
        user,
        stripe_value(current, "status"),
        current,
        subscription_id_changed=subscription_id_changed,
    )


@router.get("/me/subscription")
def get_my_subscription(
    user: User = Depends(get_current_user),
    model_bundle: ModelBundle = Depends(get_model_bundle),
):
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
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    if not all((settings.stripe_secret_key, settings.stripe_price_id_tier2,
                settings.stripe_webhook_secret)):
        raise HTTPException(status_code=503, detail="Stripe billing is not configured.")

    try:
        price = stripe.Price.retrieve(settings.stripe_price_id_tier2, api_key=settings.stripe_secret_key)
        if not is_tier2_price(price):
            raise HTTPException(status_code=503, detail="Tier 2 must be configured at $10 USD per month.")
        user = locked_user(db, user.id)
        customer_id = get_or_create_stripe_customer(db, user, settings)
        reconcile_subscription(user, settings, price)
        if user.subscription_status and user.subscription_status not in ENDED_STATUSES:
            db.commit()
            raise HTTPException(status_code=409, detail="You already have a Tier 2 subscription. Manage your existing subscription instead of subscribing again.")

        # Reuse an open checkout after a double click or a lost HTTP response.
        sessions = stripe.checkout.Session.list(
            customer=customer_id, status="open", limit=100, api_key=settings.stripe_secret_key,
        )
        for checkout in sessions.auto_paging_iter():
            metadata = stripe_value(checkout, "metadata", {})
            if (stripe_value(checkout, "mode") == "subscription"
                    and stripe_value(metadata, "tier2_price_id") == settings.stripe_price_id_tier2):
                db.commit()
                return {"url": checkout.url}

        checkout = stripe.checkout.Session.create(
            mode="subscription",
            customer=customer_id,
            client_reference_id=str(user.id),
            line_items=[{"price": settings.stripe_price_id_tier2, "quantity": 1}],
            metadata={"user_id": str(user.id), "tier2_price_id": settings.stripe_price_id_tier2},
            subscription_data={"metadata": {"user_id": str(user.id), "app": "coordinaite"}},
            success_url=f"{settings.frontend_url}/?success=true",
            cancel_url=f"{settings.frontend_url}/?canceled=true",
            api_key=settings.stripe_secret_key,
        )
        db.commit()
        return {"url": checkout.url}
    except stripe.StripeError as exc:
        db.rollback()
        raise HTTPException(status_code=502, detail="Stripe request failed. Please try again.") from exc


def process_billing_event(event, db: Session, settings: Settings) -> None:
    event_type = stripe_value(event, "type")
    if event_type not in SUBSCRIPTION_EVENTS:
        return
    obj = stripe_value(stripe_value(event, "data"), "object")
    if event_type == "charge.refunded":
        process_external_full_refund(obj, db, settings)
        return
    customer_id = stripe_id(stripe_value(obj, "customer"))
    if not customer_id:
        return
    # Only use the customer saved during authenticated checkout. Old Render
    # metadata can contain a user_id that belongs to someone else in RDS.
    user = (db.query(User).filter(User.stripe_customer_id == customer_id)
            .populate_existing().with_for_update().first())
    if user:
        reconcile_subscription(user, settings)
        db.commit()


def invoice_subscription_id(invoice) -> str | None:
    direct = stripe_id(stripe_value(invoice, "subscription"))
    if direct:
        return direct
    parent = stripe_value(invoice, "parent")
    details = stripe_value(parent, "subscription_details")
    return stripe_id(stripe_value(details, "subscription"))


def process_external_full_refund(charge, db: Session, settings: Settings) -> None:
    """Revoke access if a Tier 2 invoice is fully refunded directly in Stripe."""
    amount = int(stripe_value(charge, "amount", 0) or 0)
    refunded = int(stripe_value(charge, "amount_refunded", 0) or 0)
    if amount <= 0 or refunded < amount:
        return

    customer_id = stripe_id(stripe_value(charge, "customer"))
    invoice_id = stripe_id(stripe_value(charge, "invoice"))
    if not customer_id or not invoice_id:
        return

    user = (
        db.query(User)
        .filter(User.stripe_customer_id == customer_id)
        .populate_existing()
        .with_for_update()
        .first()
    )
    if not user or not user.stripe_subscription_id:
        return

    invoice = stripe.Invoice.retrieve(invoice_id, api_key=settings.stripe_secret_key)
    if invoice_subscription_id(invoice) != user.stripe_subscription_id:
        return
    if user.subscription_status in ENDED_STATUSES:
        return

    canceled = stripe.Subscription.delete(
        user.stripe_subscription_id,
        invoice_now=False,
        prorate=False,
        api_key=settings.stripe_secret_key,
        idempotency_key=f"coordinaite-refund-cancel-charge-{stripe_id(charge)}",
    )
    sync_user_subscription_fields(user, stripe_value(canceled, "status"), canceled)
    db.commit()


@router.post("/stripe/webhook")
async def stripe_webhook(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    if not all((settings.stripe_secret_key, settings.stripe_price_id_tier2,
                settings.stripe_webhook_secret)):
        return JSONResponse({"detail": "Stripe webhook verification is not configured."}, status_code=503)

    payload = await request.body()
    signature = request.headers.get("stripe-signature")
    if not signature:
        return JSONResponse({"detail": "Missing Stripe signature."}, status_code=400)
    try:
        event = stripe.Webhook.construct_event(
            payload=payload, sig_header=signature, secret=settings.stripe_webhook_secret,
        )
    except (ValueError, stripe.SignatureVerificationError):
        return JSONResponse({"detail": "Invalid webhook payload or signature."}, status_code=400)

    try:
        await run_in_threadpool(process_billing_event, event, db, settings)
    except stripe.StripeError:
        db.rollback()
        # Stripe retries non-2xx deliveries. Never grant access on a failed lookup.
        return JSONResponse({"detail": "Unable to verify subscription. Retry delivery."}, status_code=503)
    return JSONResponse({"status": "success"})
