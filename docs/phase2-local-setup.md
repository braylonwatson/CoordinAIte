# CoordinAIte phase 2 — local setup

This patch goes on top of your working `refactor/production-backend` branch.
It adds JWT authentication, refresh cookies, logout revocation, and account and
guest game ownership. Apply it locally before planning the Render deployment.

## 1. Apply the patch

Stop the backend and frontend with **Ctrl+C** in their respective terminals.
Keep those windows open so your local environment settings remain available.

In PowerShell:

```powershell
cd C:\Users\zakia\football-ai
git status
```

Confirm you are on `refactor/production-backend` and the working tree is clean.
If there are changes from the localhost fix, keep them and share the status
before applying; do not discard or overwrite them.

Download `coordinaite-phase2-auth-ownership.patch` to Downloads, then run:

```powershell
git am "$env:USERPROFILE\Downloads\coordinaite-phase2-auth-ownership.patch"
```

If Git reports a conflict, stop and share that output. Do not reset your branch.

## 2. Install and test

From the repository root, run these one at a time:

```powershell
.\nflenv\Scripts\Activate.ps1
cd backend
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Expected result: **36 passed**. The tests use temporary databases and fake
prediction models. They do not access your Render database or charge Stripe.

## 3. Configure the local backend

Still in `football-ai\backend`, point this window at your existing local
`coordinaite_dev` database. Enter the local PostgreSQL password when prompted:

```powershell
$localDbCredentials = Get-Credential -UserName "postgres" -Message "Enter your local PostgreSQL password"
$env:DATABASE_URL = "postgresql://postgres:$([uri]::EscapeDataString($localDbCredentials.GetNetworkCredential().Password))@127.0.0.1:5432/coordinaite_dev"
$env:APP_ENV = "development"
$env:FRONTEND_URL = "http://localhost:3000"
$env:CORS_ORIGINS = "http://localhost:3000"
$env:AUTH_COOKIE_SECURE = "false"
$env:AUTH_COOKIE_SAMESITE = "lax"
```

Add a random signing secret to the existing root `.env`. This command preserves
an existing JWT secret and the other settings. It prints no secret values:

```powershell
python -c "from pathlib import Path; from dotenv import dotenv_values, set_key; import secrets; p = Path('..') / '.env'; key = dotenv_values(p).get('JWT_SECRET_KEY') or secrets.token_urlsafe(48); assert len(key.encode()) >= 32, 'Existing JWT_SECRET_KEY is too short'; set_key(str(p), 'JWT_SECRET_KEY', key); print('JWT signing secret configured.')"
```

Keep that secret stable. Never commit `.env` or put it in a React environment
variable. If this PowerShell window already has a different `JWT_SECRET_KEY`,
remove the terminal override so the backend uses the value just configured:

```powershell
Remove-Item Env:JWT_SECRET_KEY -ErrorAction SilentlyContinue
```

## 4. Migrate and launch

Check the database target without printing credentials:

```powershell
python -c "from app.core.config import Settings; from sqlalchemy.engine import make_url; u = make_url(Settings.from_environment().database_url); assert u.host in ('localhost', '127.0.0.1') and u.database == 'coordinaite_dev', 'STOP: database is not local coordinaite_dev'; print('Confirmed: local coordinaite_dev')"
```

Only after that check succeeds, run:

```powershell
python -m alembic -c alembic.ini upgrade head
python -m alembic -c alembic.ini current
```

Expected revision: `0003_auth_sessions (head)`. Do not run `stamp` again.
The migration preserves your existing accounts and saved games. Anonymous
live games from phase one need to be started again.

Start the API:

```powershell
python -m uvicorn main:app --reload
```

Open [the readiness check](http://localhost:8000/health/ready); it should report
`"status": "ready"`. Leave this terminal running.

## 5. Start the frontend

In the other PowerShell window:

```powershell
cd C:\Users\zakia\football-ai\frontend
$env:REACT_APP_API_URL = "http://localhost:8000"
npm start
```

Open [http://localhost:3000](http://localhost:3000). Use **localhost for both
browser-facing URLs**. The old combination of localhost:3000 and
127.0.0.1:8000 prevents the default refresh cookie from working. Restart
`npm start` after changing the API environment variable.

No frontend packages were added. If dependencies need to be restored, run
`npm ci` first. Optional verification commands are:

```powershell
npm test -- --watchAll=false --runInBand
npm run build
```

Expected: **7 tests passed** and a successful build.

## 6. Check the dashboard

1. Log in with your existing local account, or create one. The old browser
   profile is deliberately cleared; the server now verifies every login.
2. Predict, log a play, save the game, and resume it.
3. Refresh the page. You should remain signed in and still see your saved games.
   The live dashboard itself does not yet automatically resume on page reload;
   use saved-game history to resume it.
4. Open an incognito window with another account. Its history must be separate.
5. As a guest, predict and log a play. Choose Save Game, sign in, then save the
   continued guest game to your account.
6. Log out, then refresh. You should stay logged out.

Report any failed step and its error. These manual checks verify your local
browser, PostgreSQL, and actual models together. Automated tests cover isolated
databases and mocked inference; they do not replace this dashboard check.

The next infrastructure milestone is Docker and CI, including PostgreSQL
concurrency tests. Before deployment, review `docs/authentication.md` for HTTPS
and the Vercel/Render domain configuration required by refresh cookies.
