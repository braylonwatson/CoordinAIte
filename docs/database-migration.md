# Database Migration Guide

The application no longer creates tables during API startup. Alembic owns every
schema change.

## Fresh local database

From `backend`:

```powershell
$env:DATABASE_URL="postgresql://postgres:password@localhost:5432/coordinaite"
python -m alembic -c alembic.ini upgrade head
python -m uvicorn main:app --reload
```

## Existing Render database

The production database already contains `users` and `saved_games`, so mark the
legacy schema as applied before creating `game_sessions`:

```bash
cd backend
python -m alembic -c alembic.ini stamp 0001_legacy_schema
python -m alembic -c alembic.ini upgrade head
```

Take a database backup first. Run `stamp` only once on the existing database.
Future releases use only:

```bash
python -m alembic -c alembic.ini upgrade head
```

For a completely new Render database, do not stamp it; run `upgrade head`
directly.

## Required production configuration

```text
DATABASE_URL=<Render internal PostgreSQL URL>
FRONTEND_URL=https://your-vercel-domain.example
CORS_ORIGINS=https://your-vercel-domain.example
APP_ENV=production
JWT_SECRET_KEY=<long-random-secret-shared-by-all-API-instances>
AUTH_COOKIE_SECURE=true
AUTH_COOKIE_SAMESITE=lax
```

Stripe also requires all three existing Stripe variables. Webhooks are rejected
unless `STRIPE_WEBHOOK_SECRET` is configured, including in local development.

## Validation

```bash
python -m alembic -c alembic.ini current
```

Expected revision:

```text
0003_auth_sessions (head)
```

Use `/health/ready` as the Render health-check path after deployment.

## Upgrading from the tested phase-one branch

The local `coordinaite_dev` database is already at `0002_game_sessions`. Run
`upgrade head` without stamping again. Revision `0003_auth_sessions` adds the
login-session table and a nullable guest-token hash column. It preserves users,
password hashes, subscription data, saved games, and account-owned live games.
Old anonymous live sessions have no private access token and must be restarted.

The frontend and backend must be upgraded together. Old requests that send
`user_id` are rejected. See [authentication.md](authentication.md) for cookie
configuration: separate Vercel/Render hostnames need a different SameSite setting
and can be affected by browser third-party-cookie restrictions.
