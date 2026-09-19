# Low latency prediction rollout

This change builds on `deploy/aws-foundation` at `6365daf`. The older `main`
branch and uploaded source files still use the pre-AWS global tracker. Do not
overwrite the AWS backend with those files.

## Implemented

- Construct a private float32 feature array in the saved training column order.
  No Pandas frame, dummy fitting, or reindex on the request path.
- Correct the old one-row `drop_first=True` bug that zeroed both team indicators.
  Predictions may change because teams now reach the models correctly. Tests
  compare every team pair with a correctly encoded Pandas reference.
- Run `predict_proba` once per model and derive the class and confidence from it.
  Preserve XGBoost's binary tie behavior and the Tier 2 label encoder.
- Load, validate column order, configure one inference thread, and warm all
  available models once at application construction.
- Return pending-play context with predictions, removing the dashboard's three
  follow-up reads on each successful prediction.
- Add HTTP `Server-Timing` plus prediction state-load, inference, commit, and
  total timings in the response. `Server-Timing` includes HTTP auth/dependencies;
  prediction timings exclude those. WebSocket `command_total` includes auth and
  thread-pool wait but excludes network transmission.
- Add optional `/ws/predictions` transport. Each command rechecks JWT expiry,
  session revocation, subscription, and ownership using the same database rules
  as REST. Credentials travel inside TLS frames, never URL query parameters.
- Reuse a live browser connection, cap it to one pending request, correlate
  replies, reject stale account/game context, and refresh expired access tokens.
  Fall back to REST only when connection setup fails before sending. A lost
  reply after sending produces an error and reads the pending state; it never
  silently submits the prediction again.
- Prepare optional ACM/Route 53/TLS ALB infrastructure exposing only the live
  route. The existing HTTP API Gateway and private REST ALB are preserved.

Game updates still commit to PostgreSQL before acknowledgment. REST log-play,
new-drive, save, history, billing, and authentication retain their existing
behavior. No database migration or model retraining is required for this change.
WebSockets carry prediction requests/replies; this does not add an automatic
live play-by-play feed, game-wide broadcast, or automatic coach input.

## Local benchmark

Run `python scripts/benchmark_inference.py --iterations 500` from the repository
root in the Python 3.11 environment. On the implementation machine, using the
saved models and warm single-threaded inference:

| Tier | Pandas + duplicate inference p50 / p95 | Array + single inference p50 / p95 |
| --- | --- | --- |
| 1 | 24.800 / 39.072 ms | 0.594 / 0.889 ms |
| 2 | 81.905 / 138.865 ms | 2.998 / 3.778 ms |

These are local microbenchmarks, not AWS or browser latency promises. The
baseline corrects team encoding too so probability parity is meaningful. No
network, database, auth, cold start, or load-balancer time is included. Results
depend on CPU and load. The script asserts output parity with the corrected
baseline; existing historical accuracy results have not been reevaluated.

The real-socket smoke check also passed against Uvicorn with the saved models
and a disposable SQLite database: HTTP prediction, WebSocket prediction,
HTTP readback of socket-created pending state, and logging the play. CI runs
the same smoke check in the Docker image against PostgreSQL, alongside backend
and frontend tests and Terraform validation. Local socket timings are not
representative of the deployed AWS network or RDS.

## Deploy the REST improvements first

1. Review/merge this branch into the AWS deployment branch. Run the backend,
   frontend, Docker/Postgres, and Terraform CI jobs.
2. Leave `realtime_enabled = false` and `REACT_APP_WS_URL` blank. Apply the
   reviewed Terraform plan if updating task environment and regenerate
   `release-config.json`; the release script clones that referenced task revision.
3. Follow `docs/aws-deployment.md` to build/push the backend image and run
   `python scripts/deploy_aws.py --image $image --tasks 2`. Two tasks add compute
   cost; models stay loaded on both, and game state remains shared in RDS.
4. Deploy the frontend from the same code, keeping its working `/api` proxy and
   cookie configuration. Prediction uses REST until the live URL is configured.
5. Check login, guest isolation, Tier 2 entitlement, prediction, log-play,
   new-drive, save/load, and logout. Measure from actual user locations.

## Enable the live route

The current HTTP API Gateway is not a transparent WebSocket tunnel. A separate
API Gateway WebSocket API would need message integrations and a different
connection-management design. This implementation uses direct ALB WebSockets.
Do not set `REACT_APP_WS_URL` to the HTTP API Gateway or the Vercel `/api` proxy.

In your existing `infra/aws/terraform.tfvars`, set:

```hcl
realtime_enabled = true
realtime_domain  = "live.coordinaite.ai" # choose an available name you own
realtime_zone_id = "YOUR_EXISTING_PUBLIC_ROUTE53_ZONE_ID"
```

From PowerShell with your AWS SSO session active:

```powershell
terraform -chdir=infra/aws plan -out=realtime.tfplan
# Review the additional ALB, certificate, DNS, security groups and service update.
terraform -chdir=infra/aws apply realtime.tfplan
terraform -chdir=infra/aws output -json release_config | Out-File -Encoding utf8 release-config.json
terraform -chdir=infra/aws output -raw realtime_url
```

This adds an internet-facing ALB and its recurring costs. It does not replace
the private REST ALB, expose RDS, or open task port 8000 to the internet. TLS
terminates at the ALB; only that ALB security group may reach the task. Unknown
public paths return 404. Application origin checks are defense in depth, not
authentication; account and guest credentials remain mandatory per command.

Regenerate `release-config.json` after applying Terraform, and update the
GitHub `AWS_DEPLOY_CONFIG` variable if using Actions. Then deploy the backend
again so the running revision receives `REALTIME_ENABLED=true` (Terraform
intentionally ignores the service's task revision). Rebuild/redeploy the Vercel
frontend with `REACT_APP_WS_URL` equal to `realtime_url`. Keep `REACT_APP_API_URL`
and authentication cookies unchanged. Allow the exact deployed frontend origin
in `CORS_ORIGINS`, not a wildcard. No credentials belong in frontend env vars.

Verify successful 101 upgrades and predictions in browser Network tools. Test
logout with an open socket and a connection loss after sending. The server
allows 10 commands/second/connection, 16 KiB messages, 10 seconds to the first
successful command, and 60 seconds idle afterward. The browser reconnects on
the next prediction after an idle closure. These per-connection limits do not
replace edge rate limiting for public high-volume clients.

Rollback: clear `REACT_APP_WS_URL` and rebuild the frontend to return to REST.
Disable `realtime_enabled` only after clients have switched, review/apply the
plan, refresh the release config, and redeploy the backend. Existing game state
remains in PostgreSQL throughout.

## Measure the deployed route

```powershell
python scripts/benchmark_api.py --url https://YOUR_HTTP_API_HOST --ws-url wss://live.coordinaite.ai/ws/predictions --origin https://YOUR_FRONTEND_HOST --requests 100
```

This creates two private disposable guest sessions and updates only their
pending predictions. It prints first-request and warm p50/p95/p99 timings,
including state-load, inference and persistence. TLS/WebSocket setup is outside
the warm round-trip measurement. Use a test deployment for concurrency runs;
the current HTTP Gateway throttles at 10 requests/sec, burst 20. The benchmark
aborts on errors rather than counting them as successful low-latency responses.
It covers Tier 1 guest access; use browser measurements for signed-in Tier 2.

## Redis and asynchronous persistence remain a separate migration

Do not turn the database commit into an untracked background task. A task
restart after a response could discard the only record of a prediction or play.
Likewise, caching `GameTracker` in each process would undo multi-task isolation.

Use deployed stage timings to decide whether RDS is the next bottleneck. A
Redis-authoritative design must switch *every* read and mutation together:
prediction, pending, state, log-play, summary, new-drive, save and load. It also
needs per-game version checks, idempotent commands, atomic state plus durable
event publication, a replayable persistence worker, acknowledged-event retry,
backlog alarms, Redis failover/recovery tests, and an explicit data-loss policy.
Redis replication alone does not guarantee zero loss of acknowledged writes.
Those pieces are not implemented or provisioned in this release.

Global Accelerator and internal gRPC are also deferred until network/service
measurements justify them. There is no extra model-service hop: inference stays
in the API process. Browser HTTP already reuses connections, so WebSockets
should be measured against warm HTTP rather than assumed universally faster.
Feed/input freshness must be measured separately from prediction latency.

References: [ALB WebSocket support](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/load-balancer-listeners.html),
[FastAPI WebSockets](https://fastapi.tiangolo.com/advanced/websockets/),
[XGBoost prediction](https://xgboost.readthedocs.io/en/stable/prediction.html).
