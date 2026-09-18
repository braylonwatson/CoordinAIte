import hashlib
import hmac
import json
import time
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import stripe

from app.db.models import User
from tests.conftest import register


PRICE = {
    "id": "price_ten", "product": "prod_tier2", "active": True,
    "currency": "usd", "unit_amount": 1000, "billing_scheme": "per_unit",
    "recurring": {"interval": "month", "interval_count": 1, "usage_type": "licensed"},
}
WEBHOOK_SECRET = "whsec_only_for_tests"


def page(items):
    return SimpleNamespace(auto_paging_iter=lambda: iter(items))


def subscription(status="active", product="prod_tier2", id="sub_current", created=2):
    return {"id": id, "customer": "cus_current", "status": status, "created": created,
            "items": {"data": [{"price": {"id": "price_ten", "product": product}}]}}


@pytest.fixture
def billing(client, app, monkeypatch):
    account = register(client)
    app.state.settings = replace(app.state.settings, stripe_secret_key="sk_test_placeholder",
                                 stripe_price_id_tier2="price_ten", stripe_webhook_secret=WEBHOOK_SECRET)
    with app.state.session_factory() as db:
        db.get(User, account["user_id"]).stripe_customer_id = "cus_current"
        db.commit()
    subscriptions = Mock(return_value=page([]))
    checkout = Mock(return_value=SimpleNamespace(url="https://checkout.stripe.com/test-session"))
    monkeypatch.setattr(stripe.Price, "retrieve", Mock(return_value=PRICE))
    monkeypatch.setattr(stripe.Subscription, "list", subscriptions)
    monkeypatch.setattr(stripe.checkout.Session, "list", Mock(return_value=page([])))
    monkeypatch.setattr(stripe.checkout.Session, "create", checkout)
    return subscriptions, checkout


def deliver(client, type="checkout.session.completed", customer="cus_current", **fields):
    payload = json.dumps({"id": "evt_repeat", "object": "event", "type": type,
                          "data": {"object": {"customer": customer, **fields}}}).encode()
    timestamp = str(int(time.time()))
    digest = hmac.new(WEBHOOK_SECRET.encode(), timestamp.encode() + b"." + payload, hashlib.sha256).hexdigest()
    return client.post("/stripe/webhook", content=payload,
                       headers={"stripe-signature": f"t={timestamp},v1={digest}", "Content-Type": "application/json"})


def test_checkout_uses_ten_dollar_price_and_return_url(client, app, billing):
    response = client.post("/create-checkout-session", json={})
    assert response.status_code == 200
    arguments = billing[1].call_args.kwargs
    assert arguments["line_items"] == [{"price": "price_ten", "quantity": 1}]
    assert arguments["success_url"] == app.state.settings.frontend_url + "/?success=true"
    assert arguments["customer"] == "cus_current"


@pytest.mark.parametrize("change", [
    {"unit_amount": 2000}, {"currency": "eur"}, {"active": False},
    {"recurring": {"interval": "year", "interval_count": 1, "usage_type": "licensed"}},
])
def test_checkout_rejects_wrong_price(client, billing, monkeypatch, change):
    monkeypatch.setattr(stripe.Price, "retrieve", Mock(return_value={**PRICE, **change}))
    assert client.post("/create-checkout-session", json={}).status_code == 503
    billing[1].assert_not_called()


def test_checkout_requires_webhook_configuration(client, app, billing):
    app.state.settings = replace(app.state.settings, stripe_webhook_secret="")
    assert client.post("/create-checkout-session", json={}).status_code == 503
    billing[1].assert_not_called()


@pytest.mark.parametrize("status", ["active", "trialing", "past_due", "unpaid", "incomplete", "paused"])
def test_existing_subscription_cannot_start_duplicate_checkout(client, billing, status):
    billing[0].return_value = page([subscription(status)])
    assert client.post("/create-checkout-session", json={}).status_code == 409
    billing[1].assert_not_called()


def test_repeated_checkout_reuses_open_session(client, billing, monkeypatch):
    existing = stripe.StripeObject.construct_from({
        "mode": "subscription", "metadata": {"tier2_price_id": "price_ten"},
        "url": "https://checkout.stripe.com/existing",
    }, None)
    monkeypatch.setattr(stripe.checkout.Session, "list", Mock(return_value=page([existing])))
    response = client.post("/create-checkout-session", json={})
    assert response.json()["url"] == existing.url
    billing[1].assert_not_called()


def test_webhook_requires_real_signature(client, billing):
    assert client.post("/stripe/webhook", json={}).status_code == 400
    assert client.post("/stripe/webhook", json={}, headers={"stripe-signature": "invalid"}).status_code == 400
    billing[0].assert_not_called()


def test_stripe_failure_does_not_grant_access_and_delivery_can_retry(client, billing):
    billing[0].side_effect = stripe.APIConnectionError("temporarily unavailable")
    assert deliver(client).status_code == 503
    assert client.get("/me/subscription").json()["tier2_access"] is False
    billing[0].side_effect = None
    billing[0].return_value = page([subscription()])
    assert deliver(client).status_code == 200
    assert client.get("/me/subscription").json()["tier2_access"] is True


def test_old_render_metadata_never_rebinds_a_new_rds_user(client, app, billing):
    response = deliver(client, customer="cus_old_render", metadata={"user_id": "1"}, client_reference_id="1")
    assert response.status_code == 200
    billing[0].assert_not_called()
    with app.state.session_factory() as db:
        assert db.get(User, 1).stripe_customer_id == "cus_current"
    assert client.get("/me/subscription").json()["tier2_access"] is False


def test_unrelated_product_does_not_grant_tier2(client, billing):
    billing[0].return_value = page([subscription(product="prod_something_else")])
    assert deliver(client).status_code == 200
    assert client.get("/me/subscription").json()["tier2_access"] is False


@pytest.mark.parametrize("event_type", ["checkout.session.completed", "customer.subscription.updated",
                                      "customer.subscription.deleted", "invoice.payment_succeeded"])
def test_late_or_duplicate_events_use_current_stripe_state(client, billing, event_type):
    billing[0].return_value = page([subscription("canceled")])
    for _ in range(2):
        assert deliver(client, type=event_type, status="active").status_code == 200
        assert client.get("/me/subscription").json()["tier2_access"] is False


def test_canceled_old_subscription_cannot_revoke_new_subscription(client, billing, app):
    billing[0].return_value = page([subscription(), subscription("canceled", id="sub_old", created=1)])
    assert deliver(client, type="customer.subscription.deleted", id="sub_old").status_code == 200
    assert client.get("/me/subscription").json()["tier2_access"] is True
    with app.state.session_factory() as db:
        assert db.get(User, 1).stripe_subscription_id == "sub_current"


def test_failed_renewal_revokes_access(client, billing):
    billing[0].return_value = page([subscription()])
    assert deliver(client).status_code == 200
    billing[0].return_value = page([subscription("past_due")])
    assert deliver(client, type="invoice.payment_failed").status_code == 200
    assert client.get("/me/subscription").json()["tier2_access"] is False
