from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import stripe

from app.db.models import RefundRequest, User
from app.services.subscriptions import sync_user_subscription_fields
from tests.conftest import register


def page(items):
    return SimpleNamespace(auto_paging_iter=lambda: iter(items))


def activate_user(app, email="owner@example.com", *, customer="cus_test", subscription="sub_test"):
    with app.state.session_factory() as db:
        user = db.query(User).filter(User.email == email).one()
        user.tier = "tier2"
        user.subscription_status = "active"
        user.stripe_customer_id = customer
        user.stripe_subscription_id = subscription
        db.commit()
        return user.id


def test_owner_users_endpoint_is_allowlisted_and_does_not_expose_secrets(client, app):
    app.state.settings = replace(app.state.settings, owner_emails=("owner@example.com",))
    owner = register(client, "owner@example.com")
    owner_token = owner["access_token"]
    register(client, "member@example.com")

    assert client.get("/owner/users").status_code == 403

    client.headers["Authorization"] = f"Bearer {owner_token}"
    response = client.get("/owner/users")
    assert response.status_code == 200
    record = next(user for user in response.json() if user["email"] == "member@example.com")
    assert record["created_at"]
    assert record["last_login_at"]
    assert record["saved_game_count"] == 0
    assert "password_hash" not in record
    assert "stripe_customer_id" not in record


def test_refund_request_requires_active_tier2_and_is_saved(client, app, monkeypatch):
    account = register(client)
    monkeypatch.setattr("app.api.routes.refunds.send_refund_request_email", Mock(return_value=True))
    assert client.post("/me/refund-request", json={"reason": "I would like to request a refund."}).status_code == 403

    activate_user(app, subscription=None, customer=None)
    response = client.post("/me/refund-request", json={"reason": "I would like to request a refund."})
    assert response.status_code == 201
    assert response.json()["status"] == "pending"
    assert response.json()["notification_sent"] is True
    assert client.get("/me/refund-request").json()["reason"] == "I would like to request a refund."
    duplicate = client.post("/me/refund-request", json={"reason": "Another refund request, please."})
    assert duplicate.status_code == 409
    with app.state.session_factory() as db:
        request = db.query(RefundRequest).one()
        assert request.user_id == account["user_id"]
        assert request.stripe_subscription_id is None
        assert request.stripe_customer_id is None
        assert request.notified_at is not None


def test_user_cannot_open_owner_refund_review_page(client, app):
    register(client, "member@example.com")
    app.state.settings = replace(app.state.settings, owner_emails=("owner@example.com",))
    assert client.get("/owner/refund-requests").status_code == 403


def test_approval_does_not_touch_a_new_subscription_started_after_request(client, app, monkeypatch):
    app.state.settings = replace(
        app.state.settings,
        owner_emails=("owner@example.com",),
        stripe_secret_key="sk_test_placeholder",
        stripe_price_id_tier2="price_tier2",
    )
    account = register(client, "owner@example.com")
    activate_user(app, subscription="sub_requested")
    request_response = client.post(
        "/me/refund-request",
        json={"reason": "I would like a refund, please."},
    )
    request_id = request_response.json()["id"]
    with app.state.session_factory() as db:
        user = db.get(User, account["user_id"])
        user.stripe_subscription_id = "sub_newer"
        db.commit()

    retrieve_subscription = Mock()
    monkeypatch.setattr(stripe.Subscription, "retrieve", retrieve_subscription)
    response = client.post(f"/owner/refund-requests/{request_id}/approve")
    assert response.status_code == 409
    retrieve_subscription.assert_not_called()


def test_refund_request_captures_the_subscription_under_review(client, app):
    account = register(client)
    activate_user(app, subscription="sub_requested")
    response = client.post(
        "/me/refund-request",
        json={"reason": "I would like a refund, please."},
    )
    assert response.status_code == 201
    with app.state.session_factory() as db:
        request = db.query(RefundRequest).one()
        assert request.user_id == account["user_id"]
        assert request.stripe_customer_id == "cus_test"
        assert request.stripe_subscription_id == "sub_requested"


def test_owner_approval_cancels_subscription_refunds_latest_paid_invoice_and_downgrades(client, app, monkeypatch):
    app.state.settings = replace(
        app.state.settings,
        owner_emails=("owner@example.com",),
        stripe_secret_key="sk_test_placeholder",
        stripe_price_id_tier2="price_tier2",
    )
    account = register(client, "owner@example.com")
    activate_user(app)
    request_response = client.post("/me/refund-request", json={"reason": "I would like a refund, please."})
    assert request_response.status_code == 201
    request_id = request_response.json()["id"]

    subscription = {
        "id": "sub_test", "customer": "cus_test", "status": "active",
        "items": {"data": [{"price": {"product": "prod_tier2"}}]},
    }
    canceled = {**subscription, "status": "canceled", "canceled_at": 1_800_000_000, "ended_at": 1_800_000_000}
    invoice = {"id": "in_latest", "amount_paid": 1000, "payment_intent": "pi_latest"}
    refund = {"id": "re_new", "payment_intent": "pi_latest", "amount": 1000, "currency": "usd", "status": "succeeded"}
    cancel_subscription = Mock(return_value=canceled)
    create_refund = Mock(return_value=refund)
    monkeypatch.setattr(stripe.Subscription, "retrieve", Mock(return_value=subscription))
    monkeypatch.setattr(stripe.Subscription, "delete", cancel_subscription)
    monkeypatch.setattr(stripe.Price, "retrieve", Mock(return_value={"id": "price_tier2", "product": "prod_tier2"}))
    monkeypatch.setattr(stripe.Invoice, "list", Mock(return_value=page([invoice])))
    monkeypatch.setattr(stripe.Refund, "list", Mock(return_value=page([])))
    monkeypatch.setattr(stripe.Refund, "create", create_refund)

    response = client.post(f"/owner/refund-requests/{request_id}/approve")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "approved"
    assert response.json()["stripe_refund_id"] == "re_new"
    assert response.json()["stripe_refund_status"] == "succeeded"
    cancel_subscription.assert_called_once()
    create_refund.assert_called_once()
    assert create_refund.call_args.kwargs["payment_intent"] == "pi_latest"
    assert create_refund.call_args.kwargs["amount"] == 1000
    with app.state.session_factory() as db:
        user = db.get(User, account["user_id"])
        assert user.tier == "free"
        assert user.subscription_status == "canceled"
        assert user.subscription_ended_at is not None


def test_failed_refund_after_successful_cancel_keeps_tier2_revoked(client, app, monkeypatch):
    app.state.settings = replace(
        app.state.settings,
        owner_emails=("owner@example.com",),
        stripe_secret_key="sk_test_placeholder",
        stripe_price_id_tier2="price_tier2",
    )
    account = register(client, "owner@example.com")
    activate_user(app)
    request_id = client.post("/me/refund-request", json={"reason": "I would like a refund, please."}).json()["id"]
    subscription = {
        "id": "sub_test", "customer": "cus_test", "status": "active",
        "items": {"data": [{"price": {"product": "prod_tier2"}}]},
    }
    canceled = {**subscription, "status": "canceled"}
    monkeypatch.setattr(stripe.Subscription, "retrieve", Mock(return_value=subscription))
    monkeypatch.setattr(stripe.Subscription, "delete", Mock(return_value=canceled))
    monkeypatch.setattr(stripe.Price, "retrieve", Mock(return_value={"id": "price_tier2", "product": "prod_tier2"}))
    monkeypatch.setattr(stripe.Invoice, "list", Mock(return_value=page([{"amount_paid": 1000, "payment_intent": "pi_latest"}])))
    monkeypatch.setattr(stripe.Refund, "list", Mock(side_effect=stripe.APIConnectionError("offline")))

    response = client.post(f"/owner/refund-requests/{request_id}/approve")
    assert response.status_code == 502
    with app.state.session_factory() as db:
        user = db.get(User, account["user_id"])
        saved_request = db.get(RefundRequest, request_id)
        assert user.tier == "free"
        assert user.subscription_status == "canceled"
        assert saved_request.status == "failed"


def test_subscription_timestamps_follow_status_transitions(app):
    with app.state.session_factory() as db:
        user = User(username="Coach", email="dates@example.com", password_hash="hash")
        db.add(user)
        db.flush()
        sync_user_subscription_fields(user, "active", {"start_date": 1_700_000_000})
        assert user.subscription_started_at is not None
        assert user.subscription_status_changed_at is not None
        sync_user_subscription_fields(user, "past_due")
        assert user.subscription_ended_at is None
        sync_user_subscription_fields(user, "canceled", {"ended_at": 1_800_000_000})
        assert user.subscription_ended_at is not None
        assert user.tier == "free"
