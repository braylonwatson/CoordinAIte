# Optional shared game snapshot cache

The API can use a private TLS Valkey (Redis protocol) cache for the four read
endpoints: `/state`, `/pending`, `/play-log`, and `/summary`. Every read first
checks ownership and the current version in PostgreSQL. The cache key includes
that database version and expires after five minutes. Prediction, log-play,
new-drive, save, subscription, and authentication operations continue to use
PostgreSQL directly. A cache outage falls back to PostgreSQL.

This avoids transferring and decoding the game JSON from PostgreSQL on a cache
hit, but adds a Redis network hop. It does not eliminate the PostgreSQL access
check or the synchronous prediction transaction. Measure actual latency and
hit rate after deployment; disable the cache if it offers no benefit.

To provision in AWS, set `game_cache_enabled = true` in the existing
`infra/aws/terraform.tfvars`. Review the Terraform plan and added monthly cost,
then apply. The node is in private subnets with TLS and at-rest encryption;
only ECS tasks may reach port 6379. This single-node cache has no replica,
which is acceptable for disposable state because PostgreSQL is authoritative.

After applying Terraform, regenerate `release-config.json` and the GitHub
`AWS_DEPLOY_CONFIG` variable as appropriate. Build and deploy a new backend
image using `scripts/deploy_aws.py`, which takes the updated Terraform API task
definition and preserves the current service count. Check readiness, guest
ownership, repeated reads, and prediction followed by state. Keep
`game_cache_enabled = false` until the release image is ready. To disable reads
without removing the node, deploy an API task definition with `REDIS_URL` empty.
