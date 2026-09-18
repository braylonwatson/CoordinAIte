# Tier 2 billing: $10 USD per month

The frontend uses Stripe-hosted Checkout. Secret keys belong only in the AWS
application secret; there is no publishable key to add to Vercel.

New Checkout sessions require an active $10 USD monthly price. The API reuses
open sessions and blocks another checkout when the customer already has a
non-ended Tier 2 subscription. Signed webhooks reconcile current Stripe state
while holding the account's database row lock. Replayed or delayed events cannot
revive a canceled subscription. Only the customer ID saved by authenticated
checkout can change access; old Render user metadata cannot bind new RDS users.

## 1. Configure the existing AWS deployment

Run from the repository root in PowerShell. These commands use your existing
AWS account and ECS/RDS deployment; no Terraform apply is needed.

```powershell
cd C:\Users\zakia\football-ai
.\nflenv\Scripts\Activate.ps1
$env:AWS_PROFILE = "coordinaite-aws"
aws sso login --profile coordinaite-aws
python -m pip install -r scripts\requirements.txt
python scripts\aws_setup.py export
```

Obtain your intended account's secret key in the
[Stripe Dashboard](https://dashboard.stripe.com/apikeys). Enter it only at the
hidden terminal prompt, never in a command argument, source file, Vercel
variable, or chat. Setup creates prices and a webhook; it does not charge a card.

If Stripe already has your Tier 2 product, find its `prod_...` ID in the product
catalog and use it so the new price stays on that product:

```powershell
python scripts\configure_stripe.py --mode live --product-id prod_REPLACE_WITH_YOUR_TIER2_PRODUCT
```

If there is no existing Tier 2 product, omit that option:

```powershell
python scripts\configure_stripe.py --mode live
```

The command creates/reuses the $10 monthly price and the webhook at
`release-config.json`'s `api_url` plus `/stripe/webhook`. It saves the Stripe key,
price ID, and webhook signing secret in Secrets Manager while preserving the
database password, JWT signing key, and other fields.

Rerunning reuses the price and webhook. If an endpoint already existed outside
this script, its signing secret is requested privately because Stripe only
returns a newly created endpoint's secret once. If a previous run failed after
creating an endpoint, retrieve its signing secret in Stripe Workbench >
Webhooks and supply it at that prompt.

Use `--mode test` for a separate development/staging deployment. Keep test and
live customer IDs in separate databases. The command rejects switching an
already configured deployment between modes or Stripe accounts.

## 2. Deploy the backend and frontend

ECS must start a new task to load the updated secret. This patch changes backend
code, so build a new image. With Docker Desktop running, execute one command at
a time and stop if one fails:

```powershell
$awsRelease = Get-Content release-config.json -Raw | ConvertFrom-Json
$ecrRegistry = ($awsRelease.repository_url -split "/")[0]
$sourceCommit = git rev-parse --short HEAD
$imageTag = "$sourceCommit-$(Get-Date -Format yyyyMMddHHmmss)"
$backendImage = "$($awsRelease.repository_url):$imageTag"
aws ecr get-login-password --region $awsRelease.region | docker login --username AWS --password-stdin $ecrRegistry
docker build --platform linux/amd64 -t $backendImage backend
docker push $backendImage
python scripts\deploy_aws.py --image $backendImage
```

Push the patched branch to GitHub and deploy/promote its latest Vercel build to
Production. The frontend build must include the $10 price and checkout-return
handling. Its API URL remains `/api`, proxied to AWS. Continue using
`https://football-ai-silk.vercel.app`.

## 3. Verify billing

1. Log in on the public frontend and open Upgrade. It should display $10/month.
2. Open Checkout and verify **$10 USD each month**. Canceling without submitting
   payment checks the price and return URL without a charge.
3. Exercise a complete payment in a separate Stripe test deployment using
   [Stripe test cards](https://docs.stripe.com/testing). A live payment is a real
   charge; perform one only when you intend to purchase the subscription.
4. Check the AWS webhook's delivery log in Stripe Workbench. Actual subscription
   events should return HTTP 200. The app polls access after Checkout returns;
   a `success=true` URL by itself never unlocks Tier 2.
5. Check Tier 2 predictions, cancellation, and a failed renewal in test mode.
   Canceling at period end retains access until Stripe marks the subscription
   canceled. Past-due/unpaid/canceled subscriptions have no Tier 2 access.

Webhook events: `checkout.session.completed`, `customer.subscription.created`,
`customer.subscription.updated`, `customer.subscription.deleted`,
`invoice.payment_failed`, and `invoice.payment_succeeded`.

Failures to read Stripe return HTTP 503 so Stripe can retry; they never activate
an unverified account. Monitor failed deliveries in Stripe Workbench and API
errors in CloudWatch. This integration reconciles state on every supported
event instead of keeping an event audit ledger.

## Existing $20 subscriptions and Render

Stripe price amounts are immutable. A new $10 price changes new checkouts;
existing subscriptions retain their old price until individually updated.
Setup reports non-ended subscriptions on other prices for the selected product.
It does not move old customers into the reset AWS database.

For an existing Tier 2 subscriber, edit their subscription in Stripe and
**replace its existing price** with the new $10 monthly price. Keep the billing
date and choose no proration if the intention is $10 on the next renewal
without an immediate charge or credit. Review the change summary before saving.
Adding another subscription item would bill both prices. Subscriptions on the
same Tier 2 product retain access during this transition.

If your own old subscription is still attached to the former Render account,
resolve that subscription before purchasing again on the new AWS account.
Deleting the Render database did not cancel Stripe billing. Once the AWS
webhook's real event deliveries pass, disable the obsolete Render webhook and
retire the old service.

References: [Manage prices](https://docs.stripe.com/products-prices/manage-prices),
[Change subscription prices](https://docs.stripe.com/billing/subscriptions/change-price),
[Webhook delivery, signatures, and retries](https://docs.stripe.com/webhooks).
