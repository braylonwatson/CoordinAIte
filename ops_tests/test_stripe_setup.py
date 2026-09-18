import json
from unittest.mock import Mock

import pytest

from scripts import configure_stripe as setup


def sdk_object(values):
    return setup.stripe.StripeObject.construct_from(values, None)


def sdk_page(values):
    return setup.stripe.ListObject.construct_from({
        "object": "list", "data": values, "has_more": False, "url": "/v1/test",
    }, None)


PRICE = {
    "id": "price_ten", "product": "prod_tier2", "active": True, "livemode": True,
    "currency": "usd", "unit_amount": 1000, "billing_scheme": "per_unit",
    "recurring": {"interval": "month", "interval_count": 1, "usage_type": "licensed"},
}


def page(items):
    result = Mock()
    result.auto_paging_iter.return_value = iter(items)
    return result


def test_secret_merge_preserves_database_jwt_and_unrelated_fields():
    client = Mock()
    old = {"database_password": "existing-db", "jwt_secret_key": "existing-jwt", "unrelated": "keep"}
    client.get_secret_value.return_value = {"SecretString": json.dumps(old)}
    setup.save_billing(client, "secret-test", {"stripe_secret_key": "sk_live_fake", "stripe_price_id_tier2": "price_ten"})
    written = json.loads(client.put_secret_value.call_args.kwargs["SecretString"])
    assert all(written[key] == value for key, value in old.items())
    assert written["stripe_price_id_tier2"] == "price_ten"


def test_uninitialized_secret_is_not_overwritten():
    client = Mock()
    client.get_secret_value.return_value = {"SecretString": "{}"}
    with pytest.raises(ValueError, match="Initialize"):
        setup.save_billing(client, "secret-test", {})
    client.put_secret_value.assert_not_called()


def test_existing_price_is_reused_and_wrong_amount_is_rejected(monkeypatch):
    create = Mock()
    monkeypatch.setattr(setup.stripe.Price, "create", create)
    monkeypatch.setattr(setup.stripe.Price, "list", Mock(return_value=page([PRICE])))
    assert setup.ensure_price(True)["id"] == "price_ten"
    create.assert_not_called()
    monkeypatch.setattr(setup.stripe.Price, "list", Mock(return_value=page([{**PRICE, "unit_amount": 2000}])))
    with pytest.raises(ValueError, match="10 USD"):
        setup.ensure_price(True)
    create.assert_not_called()


def test_price_creation_reuses_requested_product_at_ten_dollars(monkeypatch):
    monkeypatch.setattr(setup.stripe.Price, "list", Mock(return_value=page([])))
    create = Mock(return_value=PRICE)
    monkeypatch.setattr(setup.stripe.Price, "create", create)
    setup.ensure_price(True, "prod_tier2")
    arguments = create.call_args.kwargs
    assert arguments["product"] == "prod_tier2"
    assert arguments["unit_amount"] == 1000
    assert arguments["recurring"] == {"interval": "month"}


def test_mode_mismatch_is_rejected():
    with pytest.raises(ValueError, match="selected Stripe mode"):
        setup.validate_price(PRICE, False)


def test_existing_webhook_reuses_stored_signing_secret(monkeypatch):
    url = "https://aws.example/stripe/webhook"
    endpoint = {"id": "we_saved", "url": url, "enabled_events": ["invoice.payment_failed"]}
    monkeypatch.setattr(setup.stripe.WebhookEndpoint, "list", Mock(return_value=page([endpoint])))
    modify = Mock()
    monkeypatch.setattr(setup.stripe.WebhookEndpoint, "modify", modify)
    create = Mock()
    monkeypatch.setattr(setup.stripe.WebhookEndpoint, "create", create)
    prompt = Mock()
    monkeypatch.setattr(setup, "hidden_input", prompt)
    existing = {"stripe_webhook_endpoint_id": "we_saved", "stripe_account_id": "acct_test",
                "stripe_webhook_secret": "whsec_existing"}
    assert setup.ensure_webhook(url, "acct_test", existing) == ("we_saved", "whsec_existing")
    assert set(modify.call_args.kwargs["enabled_events"]) == set(setup.EVENTS)
    create.assert_not_called()
    prompt.assert_not_called()


def test_new_webhook_uses_exact_aws_url_and_supported_events(monkeypatch):
    monkeypatch.setattr(setup.stripe.WebhookEndpoint, "list", Mock(return_value=page([])))
    create = Mock(return_value={"id": "we_new", "secret": "whsec_new"})
    monkeypatch.setattr(setup.stripe.WebhookEndpoint, "create", create)
    url = "https://aws.example/stripe/webhook"
    assert setup.ensure_webhook(url, "acct_test", {}) == ("we_new", "whsec_new")
    assert create.call_args.kwargs["url"] == url
    assert set(create.call_args.kwargs["enabled_events"]) == set(setup.EVENTS)


def test_full_setup_writes_billing_without_printing_keys(monkeypatch, capsys):
    config = {"region": "us-east-1", "api_url": "https://aws.example", "application_secret_arn": "secret-test"}
    client = Mock()
    client.get_secret_value.return_value = {"SecretString": json.dumps({
        "database_password": "db-private", "jwt_secret_key": "jwt-private",
    })}
    monkeypatch.setattr(setup.boto3, "client", Mock(return_value=client))
    monkeypatch.setattr(setup, "hidden_input", Mock(return_value="sk_live_private"))
    monkeypatch.setattr(setup.stripe.Account, "retrieve", Mock(return_value={"id": "acct_test", "charges_enabled": True}))
    monkeypatch.setattr(setup, "ensure_price", Mock(return_value=PRICE))
    monkeypatch.setattr(setup, "ensure_webhook", Mock(return_value=("we_new", "whsec_private")))
    monkeypatch.setattr(setup.stripe.Subscription, "list", Mock(return_value=page([])))
    setup.configure(config, "live")
    written = json.loads(client.put_secret_value.call_args.kwargs["SecretString"])
    assert written["stripe_price_id_tier2"] == "price_ten"
    assert written["stripe_webhook_secret"] == "whsec_private"
    assert written["database_password"] == "db-private"
    output = capsys.readouterr().out
    for secret in ("sk_live_private", "whsec_private", "db-private", "jwt-private"):
        assert secret not in output
    assert "No payment was made" in output


@pytest.mark.parametrize("reuse", [False, True])
def test_setup_with_real_stripe_sdk_objects(monkeypatch, reuse):
    config = {"region": "us-east-1", "api_url": "https://aws.example", "application_secret_arn": "secret-test"}
    existing = {"database_password": "db-existing", "jwt_secret_key": "jwt-existing"}
    if reuse:
        existing.update(stripe_webhook_endpoint_id="we_test", stripe_account_id="acct_test",
                        stripe_webhook_secret="whsec_existing")
    client = Mock()
    client.get_secret_value.return_value = {"SecretString": json.dumps(existing)}
    monkeypatch.setattr(setup.boto3, "client", Mock(return_value=client))
    monkeypatch.setattr(setup, "hidden_input", Mock(return_value="sk_live_placeholder"))
    monkeypatch.setattr(setup.stripe.Account, "retrieve", Mock(return_value=sdk_object({
        "id": "acct_test", "charges_enabled": True,
    })))
    monkeypatch.setattr(setup.stripe.Product, "retrieve", Mock(return_value=sdk_object({
        "id": "prod_tier2", "active": True, "livemode": True,
    })))
    monkeypatch.setattr(setup.stripe.Price, "list", Mock(return_value=sdk_page([PRICE] if reuse else [])))
    monkeypatch.setattr(setup.stripe.Price, "create", Mock(return_value=sdk_object(PRICE)))
    monkeypatch.setattr(setup.stripe.Subscription, "list", Mock(return_value=sdk_page([{
        "id": "sub_old", "status": "active", "items": {"data": [{
            "price": {"id": "price_twenty", "product": "prod_tier2"},
        }]},
    }])))
    endpoint = {"id": "we_test", "url": config["api_url"] + "/stripe/webhook",
                "enabled_events": setup.EVENTS, "secret": "whsec_new"}
    monkeypatch.setattr(setup.stripe.WebhookEndpoint, "list", Mock(return_value=sdk_page([endpoint] if reuse else [])))
    monkeypatch.setattr(setup.stripe.WebhookEndpoint, "create", Mock(return_value=sdk_object(endpoint)))
    monkeypatch.setattr(setup.stripe.WebhookEndpoint, "modify", Mock(return_value=sdk_object(endpoint)))
    setup.configure(config, "live", "prod_tier2")
    written = json.loads(client.put_secret_value.call_args.kwargs["SecretString"])
    assert written["stripe_price_id_tier2"] == "price_ten"
    assert written["stripe_webhook_secret"] == ("whsec_existing" if reuse else "whsec_new")
    assert written["database_password"] == "db-existing"
    assert written["jwt_secret_key"] == "jwt-existing"
