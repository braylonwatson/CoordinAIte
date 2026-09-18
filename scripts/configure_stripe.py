"""Create $10/month billing and store its keys in AWS. Never prints secret values."""
import argparse
import getpass
import hashlib
import json
import warnings
from pathlib import Path
from urllib.parse import urlsplit

import boto3
from botocore.exceptions import BotoCoreError, ClientError
import stripe


ROOT = Path(__file__).resolve().parents[1]
LOOKUP_KEY = "coordinaite_tier2_usd_monthly_10"
EVENTS = [
    "checkout.session.completed",
    "customer.subscription.created",
    "customer.subscription.updated",
    "customer.subscription.deleted",
    "invoice.payment_failed",
    "invoice.payment_succeeded",
]


def hidden_input(prompt):
    # Do not allow getpass to fall back to echoing a key into terminal logs.
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        return getpass.getpass(prompt).strip()


def validate_price(price, live):
    recurring = price.get("recurring") or {}
    if not (
        price.get("active") and price.get("livemode") is live
        and price.get("currency") == "usd" and price.get("unit_amount") == 1000
        and price.get("billing_scheme") == "per_unit" and not price.get("transform_quantity")
        and recurring.get("interval") == "month" and recurring.get("interval_count") == 1
        and recurring.get("usage_type") == "licensed"
    ):
        raise ValueError("The Tier 2 price must be active, $10 USD monthly, and in the selected Stripe mode.")


def ensure_price(live, product_id=None):
    prices = list(stripe.Price.list(lookup_keys=[LOOKUP_KEY], limit=100).auto_paging_iter())
    if prices:
        price = prices[0]
        if product_id and price["product"] != product_id:
            raise ValueError("The existing CoordinAIte $10 lookup key belongs to a different product.")
    else:
        arguments = {"product": product_id} if product_id else {
            "product_data": {"name": "CoordinAIte Tier 2", "metadata": {"app": "coordinaite"}},
        }
        price = stripe.Price.create(
            **arguments, currency="usd", unit_amount=1000,
            recurring={"interval": "month"}, lookup_key=LOOKUP_KEY,
            metadata={"app": "coordinaite", "tier": "tier2"},
            idempotency_key=f"{LOOKUP_KEY}-{product_id or 'new-product'}",
        )
    validate_price(price, live)
    return price


def ensure_webhook(url, account_id, existing):
    endpoints = [endpoint for endpoint in stripe.WebhookEndpoint.list(limit=100).auto_paging_iter()
                 if endpoint["url"] == url]
    if len(endpoints) > 1:
        raise ValueError("Multiple Stripe webhooks use this AWS URL. Keep one endpoint in Stripe before rerunning.")
    if endpoints:
        endpoint = endpoints[0]
        same_endpoint = (existing.get("stripe_webhook_endpoint_id") == endpoint["id"]
                         and existing.get("stripe_account_id") == account_id)
        secret = existing.get("stripe_webhook_secret") if same_endpoint else None
        if not secret:
            secret = hidden_input("Existing AWS webhook signing secret (whsec_...): ")
        if not secret.startswith("whsec_"):
            raise ValueError("A webhook signing secret beginning with whsec_ is required.")
        events = endpoint["enabled_events"]
        stripe.WebhookEndpoint.modify(
            endpoint["id"], disabled=False,
            enabled_events=events if "*" in events else sorted(set(events) | set(EVENTS)),
        )
    else:
        token = hashlib.sha256(url.encode()).hexdigest()[:24]
        endpoint = stripe.WebhookEndpoint.create(
            url=url, enabled_events=EVENTS, api_version=stripe.api_version,
            description="CoordinAIte AWS subscription billing",
            metadata={"app": "coordinaite"},
            idempotency_key=f"coordinaite-aws-webhook-{token}",
        )
        secret = endpoint["secret"]
    return endpoint["id"], secret


def save_billing(secrets_client, secret_id, billing):
    # Re-read just before merging. Database/JWT credentials and any other fields
    # survive; this is not a replacement with a three-field Stripe-only secret.
    current = secrets_client.get_secret_value(SecretId=secret_id)
    values = json.loads(current["SecretString"])
    if not values.get("database_password") or not values.get("jwt_secret_key"):
        raise ValueError("Initialize the application secret before configuring billing.")
    values.update(billing)
    secrets_client.put_secret_value(SecretId=secret_id, SecretString=json.dumps(values))


def configure(config, mode, product_id=None):
    api_url = config["api_url"].rstrip("/")
    parsed = urlsplit(api_url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError("release-config.json must contain the HTTPS AWS API URL.")
    client = boto3.client("secretsmanager", region_name=config["region"])
    secret_id = config["application_secret_arn"]
    existing = json.loads(client.get_secret_value(SecretId=secret_id)["SecretString"])
    if not existing.get("database_password") or not existing.get("jwt_secret_key"):
        raise ValueError("Initialize the application secret before configuring billing.")
    old_key = existing.get("stripe_secret_key") or ""
    prefix = f"sk_{mode}_"
    if old_key and not old_key.startswith(prefix):
        raise ValueError("This AWS deployment already uses a different Stripe mode. Use a separate test deployment.")
    key = hidden_input(f"Stripe {mode} secret key (sk_{mode}_...; Enter keeps an existing key): ") or old_key
    if not key.startswith(prefix):
        raise ValueError(f"Use a Stripe secret key beginning with {prefix} for this mode.")
    stripe.api_key = key
    stripe.max_network_retries = 2
    account = stripe.Account.retrieve()
    if mode == "live" and not account.get("charges_enabled"):
        raise ValueError("Activate live payments in your Stripe Dashboard before running live setup.")
    if existing.get("stripe_account_id") and existing["stripe_account_id"] != account["id"]:
        raise ValueError("This deployment is already connected to a different Stripe account.")
    # When reconnecting an already configured deployment, retain the Tier 2 product.
    if not product_id and existing.get("stripe_price_id_tier2"):
        product_id = stripe.Price.retrieve(existing["stripe_price_id_tier2"])["product"]
    if product_id:
        product = stripe.Product.retrieve(product_id)
        if not product.get("active") or product.get("livemode") is not (mode == "live"):
            raise ValueError("The selected Tier 2 product must be active and in the selected Stripe mode.")
    print(f"Stripe account: {account['id']}. Mode: {mode}. Tier 2: $10 USD/month.")
    price = ensure_price(mode == "live", product_id)
    # Report existing subscriptions without migrating or charging them implicitly.
    older = []
    for subscription in stripe.Subscription.list(status="all", limit=100).auto_paging_iter():
        if subscription["status"] in {"canceled", "incomplete_expired"}:
            continue
        for item in subscription["items"]["data"]:
            if item["price"]["product"] == price["product"] and item["price"]["id"] != price["id"]:
                older.append(subscription["id"])
                break
    webhook_url = api_url + "/stripe/webhook"
    endpoint_id, webhook_secret = ensure_webhook(webhook_url, account["id"], existing)
    save_billing(client, secret_id, {
        "stripe_secret_key": key,
        "stripe_price_id_tier2": price["id"],
        "stripe_webhook_secret": webhook_secret,
        "stripe_webhook_endpoint_id": endpoint_id,
        "stripe_account_id": account["id"],
    })
    print(f"Price ready: {price['id']} ($10 USD/month).")
    print(f"Webhook ready: {webhook_url} ({endpoint_id}).")
    print("Billing credentials saved in Secrets Manager. Existing database and JWT credentials preserved.")
    if older:
        print("Existing subscriptions still on another price: " + ", ".join(older))
        print("Change their existing subscription item to the new price in Stripe; see docs/stripe-billing.md.")
    if not product_id:
        print("Created/reused the CoordinAIte product. Review any older Render subscriptions separately in Stripe.")
    print("Deploy the updated backend image to load these settings. No payment was made by this command.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["test", "live"], required=True)
    parser.add_argument("--product-id", help="Reuse your existing Tier 2 prod_... product, if any.")
    parser.add_argument("--config", type=Path, default=ROOT / "release-config.json")
    args = parser.parse_args()
    try:
        configure(json.loads(args.config.read_text(encoding="utf-8-sig")), args.mode, args.product_id)
    except (stripe.StripeError, BotoCoreError, ClientError) as error:
        # Avoid exception bodies: SDK errors can contain request or credential details.
        raise SystemExit(f"Setup stopped ({type(error).__name__}). Check AWS SSO login and Stripe key permissions, then retry.") from None
    except (ValueError, OSError, getpass.GetPassWarning) as error:
        raise SystemExit(f"Setup stopped: {error}") from None


if __name__ == "__main__":
    main()
