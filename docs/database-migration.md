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
```

Stripe also requires all three existing Stripe variables. Webhooks are rejected
unless `STRIPE_WEBHOOK_SECRET` is configured, including in local development.

## Validation

```bash
python -m alembic -c alembic.ini current
```

Expected revision:

```text
0002_game_sessions (head)
```

Use `/health/ready` as the Render health-check path after deployment.
