# Authentication and game ownership

This milestone adds authentication and authorization to the phase-one stateless
backend. It is an incremental local release; production deployment still needs
rate limiting, recovery/verification, monitoring, and deployment checks.

## Request identity

Signup and login verify credentials, create an `auth_sessions` row, and return a
15-minute HS256 JWT. The token contains the user ID, login-session ID, issuer,
audience, issue time, expiry, and access-token type. The server pins the algorithm
and verifies every required claim. Never put the signing key in the React build.

React keeps the access token in memory and sends it in `Authorization: Bearer …`.
The backend looks up the referenced login session, rejects expired/revoked
sessions, and resolves the user itself. This database lookup makes logout
effective across workers. It remains a stateless API deployment: no mutable
per-user state is held inside a worker.

Subscription rights come from the current database record, not token claims or
client fields. Changing an account ID in a request cannot change its identity.

## Refresh and logout

The refresh credential is an opaque random secret in an HttpOnly, host-only
cookie scoped to `/auth`. Only a SHA-256 hash is stored in PostgreSQL. Refresh
locks the login-session row, validates the current hash, rotates the secret,
and returns a new access token. Sessions expire after a fixed seven days;
refresh does not extend that absolute expiry.

Previously used refresh values return 401. They do not revoke the current
session: retaining token history and revoking a whole family after confirmed
reuse is future work. This avoids treating an arbitrary invalid secret as
authority to log someone else out.

The client shares one refresh operation between simultaneous requests. Where
the browser supports Web Locks, tabs also coordinate cookie mutations. A 401
triggers at most one retry. A refreshed identity from a different account never
replays an in-flight mutation. If restoration fails, the UI asks for login.

`POST /auth/logout` revokes the presented login session and expires the refresh
cookie. Other device sessions remain active. Access and refresh tokens are not
stored in localStorage or sessionStorage. The guest-mode UI flag is not an
authentication credential.

Cookie-writing endpoints require `X-CSRF-Protection: 1`. When Origin is present,
it must match a configured frontend origin. Requiring the custom header forces
browser preflight; the explicit Origin check also rejects forbidden requests
on the server. Ordinary authenticated endpoints accept bearer credentials,
not cookies alone.

## Ownership

| Operation | Required authority |
| --- | --- |
| Create account-owned live game | Verified account token |
| Create anonymous live game | Public; returns a new private guest token |
| Read/predict/log/start drive | Owning account, or that guest game's token |
| Save a live game | Verified account and access to that live game |
| List/resume/delete saves | Owning account |
| Tier 2 prediction | Access to game and current active subscription |
| View subscription/start checkout | Verified account; no client-selected owner |

Guest secrets are sent in `X-Game-Token`, never a URL. Only their hash is stored.
Knowing a game UUID alone does not authorize access. A guest can sign in and
save the current game; claiming it clears the guest hash so only its new owner
can access it. Old anonymous sessions without a hash are inaccessible after
the migration; guests should create a new game. Existing saved games remain.

## API changes

- `/signup` and `/login` now return `access_token`, `token_type`, and `expires_in`
  with the profile; they also set the refresh cookie.
- New endpoints: `GET /me`, `POST /auth/refresh`, `POST /auth/logout`.
- List the signed-in user's saves with `GET /games`.
- Stop sending `user_id` in request bodies, paths, or query strings.
- `POST /games` requires the source live `game_id` and checks access before saving.
- `POST /create-checkout-session` accepts an empty JSON object.
- `POST /set-teams` returns `guest_token` only for anonymous games.
- Inaccessible live and saved game IDs return 404; missing/invalid login
  credentials on account endpoints return 401; unavailable subscription rights
  return 403.

## Configuration

| Variable | Value |
| --- | --- |
| `JWT_SECRET_KEY` | Required random secret, at least 32 bytes; identical on every worker |
| `ACCESS_TOKEN_MINUTES` | Default 15; allowed 1–60 |
| `REFRESH_TOKEN_DAYS` | Default 7; allowed 1–30 |
| `JWT_ISSUER` | Default `coordinaite` |
| `JWT_AUDIENCE` | Default `coordinaite-api` |
| `AUTH_COOKIE_SECURE` | `false` for local HTTP; `true` in production |
| `AUTH_COOKIE_SAMESITE` | `lax` for the same site; `none` requires Secure |
| `CORS_ORIGINS` | Exact frontend origins, never `*` |

Use `http://localhost:3000` and `http://localhost:8000` together locally.
Mixing a localhost frontend with a 127.0.0.1 API breaks SameSite=Lax refresh.
Run the backend on `127.0.0.1`; the browser can reach it as `localhost`.

For production, serve the frontend and API under the same site, such as
`app.your-domain.com` and `api.your-domain.com`, with HTTPS. They can still be
hosted on Vercel and Render. Keep the refresh cookie host-only on the API.
Unrelated `vercel.app` / `onrender.com` hostnames require
`AUTH_COOKIE_SAMESITE=none` and `AUTH_COOKIE_SECURE=true`, but some browsers block
third-party cookies. That configuration must be checked in target browsers
before deployment; a shared parent domain avoids depending on those cookies.
The default API address changed to localhost; restart CRA after changing
`REACT_APP_API_URL`.

Do not rotate `JWT_SECRET_KEY` on every restart. Changing it invalidates access
tokens until clients refresh. All instances must share the same value. Logout
or database session expiry remains the way to revoke refresh sessions.

## Verification scope

Run `python -m pytest -q` from `backend`. The tests use isolated SQLite databases
and fake prediction models; no Render database or Stripe account is contacted.
They cover token validation, refresh rotation/replay, CSRF, immediate revocation,
cross-instance persistence, every game ownership route, guest claiming, current
subscription checks, billing identity, and fresh/existing database migrations.
SQLite tests do not establish PostgreSQL row-lock behavior under load. Run that
concurrency check with PostgreSQL when adding the Docker integration milestone.

Run `npm test -- --watchAll=false --runInBand` and `npm run build` from `frontend`.
API-client tests cover refresh concurrency, account switching, late refresh
after logout, and guest credentials. Browser cookie behavior and the complete
dashboard still need the local manual checks in the setup guide.

## References

- [FastAPI's JWT authentication guide](https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/)
- [PyJWT verification options](https://pyjwt.readthedocs.io/en/stable/api.html)
- [Cookie attributes and browser behavior](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Set-Cookie)
