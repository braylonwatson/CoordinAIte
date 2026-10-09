from datetime import datetime, timezone
import smtplib

from fastapi import APIRouter, Depends, HTTPException
import stripe
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, get_db, get_owner_user, get_settings
from app.core.config import Settings
from app.db.models import RefundRequest, SavedGame, User, utc_now
from app.schemas import RefundRequestCreate
from app.services.refund_email import send_refund_request_email
from app.services.subscriptions import (
    stripe_id,
    stripe_value,
    subscription_has_product,
    subscription_is_active,
    sync_user_subscription_fields,
)


router = APIRouter(tags=["refunds and owner tools"])
FINAL_REQUEST_STATES = {"approved", "denied"}


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def serialize_refund_request(request: RefundRequest, user: User | None = None) -> dict:
    return {
        "id": request.id,
        "user_id": request.user_id,
        "username": user.username if user else None,
        "email": user.email if user else None,
        "reason": request.reason,
        "status": request.status,
        "created_at": iso(request.created_at),
        "notified_at": iso(request.notified_at),
        "reviewed_at": iso(request.reviewed_at),
        "stripe_refund_id": request.stripe_refund_id,
        "stripe_refund_status": request.stripe_refund_status,
        "refund_amount_cents": request.refund_amount_cents,
        "refund_currency": request.refund_currency,
        "resolution_message": request.resolution_message,
    }


@router.get("/me/refund-request")
def get_my_refund_request(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    request = (
        db.query(RefundRequest)
        .filter(RefundRequest.user_id == user.id)
        .order_by(RefundRequest.id.desc())
        .first()
    )
    return serialize_refund_request(request) if request else None


@router.post("/me/refund-request", status_code=201)
def create_refund_request(
    data: RefundRequestCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    if not subscription_is_active(user.subscription_status) or user.tier != "tier2":
        raise HTTPException(status_code=403, detail="An active Tier 2 subscription is required to request a refund.")

    existing = (
        db.query(RefundRequest)
        .filter(
            RefundRequest.user_id == user.id,
            RefundRequest.status.in_(["pending", "processing"]),
        )
        .order_by(RefundRequest.id.desc())
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="You already have a refund request awaiting review.")

    request = RefundRequest(
        user_id=user.id,
        reason=data.reason,
        stripe_customer_id=user.stripe_customer_id,
        stripe_subscription_id=user.stripe_subscription_id,
    )
    db.add(request)
    db.commit()
    db.refresh(request)

    notification_sent = False
    try:
        notification_sent = send_refund_request_email(request, user, settings)
    except (smtplib.SMTPException, OSError):
        # The request remains durably visible in the owner page if mail is down.
        notification_sent = False
    if notification_sent:
        request.notified_at = utc_now()
        db.commit()

    return {
        **serialize_refund_request(request),
        "notification_sent": notification_sent,
        "message": (
            "Your request was sent to support for owner review."
            if notification_sent
            else "Your request is saved for owner review, but the support email could not be sent."
        ),
    }


@router.get("/owner/users")
def list_users(
    _: User = Depends(get_owner_user),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(User, func.count(SavedGame.id).label("saved_game_count"))
        .outerjoin(SavedGame, SavedGame.user_id == User.id)
        .group_by(User.id)
        .order_by(User.id.desc())
        .all()
    )
    return [
        {
            "user_id": user.id,
            "username": user.username,
            "email": user.email,
            "tier": user.tier or "free",
            "subscription_status": user.subscription_status,
            "created_at": iso(user.created_at),
            "updated_at": iso(user.updated_at),
            "subscription_started_at": iso(user.subscription_started_at),
            "subscription_ended_at": iso(user.subscription_ended_at),
            "subscription_status_changed_at": iso(user.subscription_status_changed_at),
            "last_login_at": iso(user.last_login_at),
            "saved_game_count": saved_game_count,
            "has_stripe_subscription": bool(user.stripe_subscription_id),
        }
        for user, saved_game_count in rows
    ]


@router.get("/owner/refund-requests")
def list_refund_requests(
    _: User = Depends(get_owner_user),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(RefundRequest, User)
        .join(User, User.id == RefundRequest.user_id)
        .order_by(RefundRequest.id.desc())
        .limit(250)
        .all()
    )
    return [serialize_refund_request(request, user) for request, user in rows]


def invoice_subscription_id(invoice) -> str | None:
    direct = stripe_id(stripe_value(invoice, "subscription"))
    if direct:
        return direct
    parent = stripe_value(invoice, "parent")
    details = stripe_value(parent, "subscription_details")
    return stripe_id(stripe_value(details, "subscription"))


def invoice_payment(invoice) -> tuple[str | None, str | None]:
    """Return (payment intent ID, charge ID), handling both Stripe invoice formats."""
    intent_id = stripe_id(stripe_value(invoice, "payment_intent"))
    charge_id = stripe_id(stripe_value(invoice, "charge"))
    if intent_id or charge_id:
        return intent_id, charge_id

    payments = stripe_value(stripe_value(invoice, "payments"), "data", []) or []
    for invoice_payment in payments:
        payment = stripe_value(invoice_payment, "payment")
        intent_id = stripe_id(stripe_value(payment, "payment_intent"))
        charge_id = stripe_id(stripe_value(payment, "charge"))
        if intent_id or charge_id:
            return intent_id, charge_id
    return None, None


def latest_paid_payment(
    customer_id: str,
    subscription_id: str,
    settings: Settings,
    subscription,
) -> tuple[int, str, str] | None:
    price = stripe.Price.retrieve(settings.stripe_price_id_tier2, api_key=settings.stripe_secret_key)
    product_id = stripe_id(stripe_value(price, "product"))
    if not product_id or not subscription_has_product(subscription, product_id):
        raise HTTPException(status_code=409, detail="The linked Stripe subscription is not CoordinAIte Tier 2.")

    invoices = stripe.Invoice.list(
        customer=customer_id,
        subscription=subscription_id,
        status="paid",
        limit=100,
        api_key=settings.stripe_secret_key,
    )
    for invoice in invoices.auto_paging_iter():
        amount_paid = int(stripe_value(invoice, "amount_paid", 0) or 0)
        intent_id, charge_id = invoice_payment(invoice)
        payment_id = intent_id or charge_id
        if amount_paid > 0 and payment_id:
            return amount_paid, "payment_intent" if intent_id else "charge", payment_id
    return None


def refund_for_payment(request: RefundRequest, amount_paid: int, payment_type: str, payment_id: str, settings: Settings):
    list_args = {payment_type: payment_id, "limit": 100, "api_key": settings.stripe_secret_key}
    prior_refunds = stripe.Refund.list(**list_args)
    refunds = list(prior_refunds.auto_paging_iter())

    for existing in refunds:
        metadata = stripe_value(existing, "metadata", {}) or {}
        if str(stripe_value(metadata, "refund_request_id", "")) == str(request.id):
            status = stripe_value(existing, "status")
            if status in {"succeeded", "pending", "requires_action"}:
                return existing
            raise HTTPException(status_code=502, detail="Stripe reports the prior refund attempt failed. Review it in Stripe before retrying.")

    already_refunded = sum(
        int(stripe_value(item, "amount", 0) or 0)
        for item in refunds
        if stripe_value(item, "status") not in {"failed", "canceled"}
    )
    remaining = max(0, amount_paid - already_refunded)
    if remaining == 0:
        return max(refunds, key=lambda item: int(stripe_value(item, "created", 0) or 0), default=None)

    return stripe.Refund.create(
        **{payment_type: payment_id},
        amount=remaining,
        reason="requested_by_customer",
        metadata={"app": "coordinaite", "refund_request_id": str(request.id), "user_id": str(request.user_id)},
        idempotency_key=f"coordinaite-refund-request-{request.id}",
        api_key=settings.stripe_secret_key,
    )


@router.post("/owner/refund-requests/{request_id}/approve")
def approve_refund_request(
    request_id: int,
    owner: User = Depends(get_owner_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    request = (
        db.query(RefundRequest)
        .filter(RefundRequest.id == request_id)
        .with_for_update()
        .first()
    )
    if not request:
        raise HTTPException(status_code=404, detail="Refund request not found.")
    if request.status == "approved":
        return serialize_refund_request(request)
    if request.status == "denied":
        raise HTTPException(status_code=409, detail="This refund request was already denied.")

    user = (
        db.query(User)
        .filter(User.id == request.user_id)
        .populate_existing()
        .with_for_update()
        .one()
    )
    target_subscription_id = request.stripe_subscription_id
    target_customer_id = request.stripe_customer_id
    if (
        user.stripe_subscription_id
        and user.stripe_subscription_id != target_subscription_id
        and subscription_is_active(user.subscription_status)
    ):
        raise HTTPException(
            status_code=409,
            detail="This account has a different active subscription than the one on the request. Review the subscription change before approving.",
        )
    if target_subscription_id and not all((settings.stripe_secret_key, settings.stripe_price_id_tier2)):
        raise HTTPException(status_code=503, detail="Stripe is not configured to process this refund.")

    subscription = None
    refund = None
    amount_paid = 0
    cancellation_completed = False
    try:
        if target_subscription_id:
            subscription = stripe.Subscription.retrieve(
                target_subscription_id,
                api_key=settings.stripe_secret_key,
            )
            if stripe_id(stripe_value(subscription, "customer")) != target_customer_id:
                raise HTTPException(status_code=409, detail="The Stripe subscription does not belong to this account.")

            payment = latest_paid_payment(
                target_customer_id,
                target_subscription_id,
                settings,
                subscription,
            )
            if payment:
                amount_paid, payment_type, payment_id = payment

            status = stripe_value(subscription, "status")
            if status not in {"canceled", "incomplete_expired"}:
                subscription = stripe.Subscription.delete(
                    target_subscription_id,
                    invoice_now=False,
                    prorate=False,
                    api_key=settings.stripe_secret_key,
                    idempotency_key=f"coordinaite-refund-cancel-{request.id}",
                )
            cancellation_completed = True

            if payment:
                refund = refund_for_payment(request, amount_paid, payment_type, payment_id, settings)
        else:
            # Manually granted Tier 2 accounts have nothing Stripe can refund.
            cancellation_completed = True

        if not user.stripe_subscription_id or user.stripe_subscription_id == target_subscription_id:
            if target_subscription_id:
                sync_user_subscription_fields(user, stripe_value(subscription, "status"), subscription)
            else:
                sync_user_subscription_fields(user, None)
        if not subscription_is_active(user.subscription_status):
            user.tier = "free"

        request.status = "approved"
        request.reviewed_at = utc_now()
        request.reviewed_by_user_id = owner.id
        request.stripe_refund_id = stripe_id(refund)
        request.stripe_refund_status = stripe_value(refund, "status") if refund else None
        request.stripe_payment_intent_id = (
            stripe_id(stripe_value(refund, "payment_intent"))
            if refund else None
        )
        request.refund_amount_cents = int(stripe_value(refund, "amount", 0) or 0) if refund else 0
        request.refund_currency = stripe_value(refund, "currency") if refund else None
        if not refund:
            request.resolution_message = (
                "Subscription canceled and Tier 2 access removed; no successful Stripe payment was found to refund."
            )
        elif request.stripe_refund_status == "succeeded":
            request.resolution_message = (
                "Subscription canceled, Tier 2 access removed, and the latest eligible payment was refunded in Stripe."
            )
        else:
            request.resolution_message = (
                "Subscription canceled and Tier 2 access removed. The Stripe refund was submitted with status "
                f"{request.stripe_refund_status or 'unknown'}; check Stripe for its final settlement."
            )
        db.commit()
        db.refresh(request)
        return serialize_refund_request(request, user)
    except stripe.StripeError as exc:
        db.rollback()
        if cancellation_completed:
            # Do not restore access if cancellation succeeded but the refund API
            # failed. The owner can retry the request or resolve it in Stripe.
            user = db.query(User).filter(User.id == request.user_id).with_for_update().one()
            if target_subscription_id and (
                not user.stripe_subscription_id or user.stripe_subscription_id == target_subscription_id
            ):
                user.subscription_status = "canceled"
                user.tier = "free"
                user.subscription_status_changed_at = utc_now()
                user.subscription_ended_at = utc_now()
            elif not user.stripe_subscription_id:
                user.subscription_status = None
                user.tier = "free"
                user.subscription_status_changed_at = utc_now()
            else:
                user.tier = "free"
            request = db.query(RefundRequest).filter(RefundRequest.id == request_id).with_for_update().one()
            request.status = "failed"
            request.reviewed_by_user_id = owner.id
            request.resolution_message = "Subscription access was removed, but Stripe could not complete the refund. Retry review or resolve it in Stripe."
            db.commit()
        else:
            request.status = "failed"
            request.reviewed_by_user_id = owner.id
            request.resolution_message = "Stripe could not complete the request. Tier 2 access was not changed; retry review."
            db.commit()
        raise HTTPException(status_code=502, detail="Stripe could not complete the refund action. The request remains available for owner review.") from exc
    except HTTPException:
        db.rollback()
        raise


@router.post("/owner/refund-requests/{request_id}/deny")
def deny_refund_request(
    request_id: int,
    owner: User = Depends(get_owner_user),
    db: Session = Depends(get_db),
):
    request = (
        db.query(RefundRequest)
        .filter(RefundRequest.id == request_id)
        .with_for_update()
        .first()
    )
    if not request:
        raise HTTPException(status_code=404, detail="Refund request not found.")
    if request.status == "approved":
        raise HTTPException(status_code=409, detail="This request was already approved and processed.")
    if request.status == "denied":
        return serialize_refund_request(request)
    request.status = "denied"
    request.reviewed_at = utc_now()
    request.reviewed_by_user_id = owner.id
    request.resolution_message = "The refund request was declined by the owner."
    db.commit()
    db.refresh(request)
    return serialize_refund_request(request)
