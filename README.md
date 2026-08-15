# Spenza — Expense Tracker REST API

A production-ready FastAPI backend with dual-token (access + refresh) cookie
authentication, email OTP verification, and a full password-reset flow.
Built with a repository-service pattern and feature-module layout so new
domains (Accounts, Categories, Transactions, Budgets, Reports, ...) can be
added under `src/modules/` without touching what's already here.

## Tech Stack

- Python 3.13, FastAPI, Uvicorn/Gunicorn
- PostgreSQL + SQLAlchemy 2.0 (async, `asyncpg`) + Alembic
- Pydantic v2 / `pydantic-settings`
- JWT (`PyJWT`) access tokens + hashed opaque refresh tokens
- Argon2id password hashing (`argon2-cffi`)
- `slowapi` rate limiting, `structlog` structured logging
- `uv` for dependency management, `pytest` + `pytest-asyncio` + `pytest-cov`
- `ruff` + `mypy` + `pre-commit`

## Architecture

```text
src/
  app.py                    FastAPI app factory + process entry points
  lifespan.py                startup/shutdown hooks
  core/                       cross-cutting infra (config, db, security, ...)
    app_config.py             pydantic-settings Settings (single source of truth)
    database.py                async engine/session, Base, UTCDateTime type
    security.py                password hashing, JWT, OTP, refresh-token hashing
    exceptions.py               AppError hierarchy
    exception_handlers.py       translates exceptions -> {success,message,error_code}
    responses.py                 SuccessResponse[T] / ErrorResponse envelopes
    middleware.py                 request-id + security headers
    rate_limit.py                  shared slowapi Limiter
    logger.py                       stdlib logging.yaml + structlog setup
  modules/
    users/                     signup, auth, password, profile (repository-service)
      models.py, schemas.py, repository.py, service.py, dependencies.py, router.py
  shared/
    email/                     EmailBackend (console/SMTP) + Jinja2 templates
  db/base.py                  Alembic's single metadata import point
```

Each future domain module (`accounts`, `categories`, `transactions`, ...) follows
the same shape as `modules/users`: models -> repository -> service -> router,
registered independently in `src/app.py`.

## Authentication Model

Dual-token, cookie-based — the "stay signed in like ChatGPT/Claude" pattern:

- **Access token**: JWT, 15 min, HttpOnly cookie, bound to a session id.
- **Refresh token**: opaque random token, 30 days, HttpOnly cookie, **hashed**
  before storage, **rotated on every use** (old token is immediately revoked).
- A `refresh_sessions` row exists per device/session — supports multi-device
  login, per-device logout, and "logout everywhere."
- Password change or reset revokes **all** sessions immediately, forcing
  re-login — access tokens are checked against their session's revocation
  state on every request, not just at expiry.
- `/login` and `/login-json` accept either an email or a username in the
  same `identifier` field — whichever the user types.

### Admin access

Every user has a `role`: `user` (default) or `admin`. There's no signup-time
way to become an admin — the *first* admin must be promoted from the CLI:

```bash
make promote-admin EMAIL=someone@example.com
```

To remove admin access, demote them back to a regular user:

```bash
make demote-admin EMAIL=someone@example.com
```

This refuses if they're the only admin left, so you can't accidentally lock
yourself out of the admin API entirely. Once at least one admin exists, roles
can also be changed by another admin via
`PATCH /api/v1/admin/users/{id}/role` — same last-admin guard, plus an admin
can never change their own role.

Admin-only routes (`/api/v1/admin/...`) sit behind the same access-token
cookie as everything else, plus a role check — a non-admin gets `403
ADMIN_PRIVILEGES_REQUIRED`, an unauthenticated request gets `401`.

## Getting Started

```bash
# 1. Install dependencies (creates .venv, installs dev + runtime deps)
make install

# 2. Copy the env template and fill in real values
cp .env.example .env

# 3. Start Postgres (or point DATABASE_URL at an existing instance)
docker run -d --name spenza-postgres -e POSTGRES_PASSWORD=postgres \
  -p 5432:5432 postgres:17

# 4. Run migrations
make migrate

# 5. (optional) seed a few demo accounts
make seed

# 6. Run the dev server
make dev
```

The API is now at `http://localhost:8000`:

- Swagger UI: `/docs`
- ReDoc: `/redoc`
- Raw OpenAPI JSON: `/openapi.json` (a snapshot is also checked in at
  `docs/openapi.json`)
- Health check: `/health`

### Email in development

`EMAIL_BACKEND=console` (the default) logs the rendered OTP/reset/welcome
email instead of sending it — read the OTP straight from the server log.
Set `EMAIL_BACKEND=smtp` with real Gmail SMTP credentials for production.

## Makefile targets

| Command                        | Description                                |
| ------------------------------ | ------------------------------------------ |
| `make install`                 | `uv sync` + install pre-commit hooks       |
| `make dev`                     | Run with autoreload (uvicorn)              |
| `make run`                     | Run via the app's own prod/dev entrypoint  |
| `make migrate`                 | Apply Alembic migrations                   |
| `make migrate-new name="..."`  | Autogenerate a new migration               |
| `make seed`                    | Seed demo accounts                         |
| `make promote-admin EMAIL=...` | Promote an existing user to the admin role |
| `make demote-admin EMAIL=...`  | Demote an admin back to a regular user     |
| `make cleanup-otps`            | Delete stale/abandoned `email_otps` rows   |
| `make test`                    | Run the test suite                         |
| `make test-cov`                | Run tests with coverage report (90% gate)  |
| `make lint`                    | `ruff check`                               |
| `make format`                  | `ruff format`                              |
| `make typecheck`               | `mypy src`                                 |
| `make check`                   | lint + typecheck + test-cov                |
| `make precommit`               | Run all pre-commit hooks                   |

## API Endpoints

All routes are under `/api/users` and return the envelope
`{"success": bool, "message": str, "data"?: ..., "error_code"?: str}`.

**Auth**
`POST /signup` · `POST /verify-signup-otp` · `POST /login` ·
`POST /login-json` · `POST /refresh-token` · `POST /logout` ·
`POST /logout-all-devices` · `GET /me`

**Password**
`POST /forgot-password` · `POST /verify-reset-otp` · `POST /reset-password` ·
`POST /change-password`

**User**
`PATCH /update-username` · `PATCH /update-profile` · `DELETE /delete-user` ·
`GET /profile`

**Admin** (all under `/api/v1/admin/...`, requires the `admin` role — see
[Admin access](#admin-access) below)

- Users (`/api/v1/admin/users`): `GET /` (list, paginated) · `GET /{id}` ·
  `PATCH /{id}/active` · `PATCH /{id}/role` · `POST /{id}/unlock` ·
  `GET /{id}/sessions` · `DELETE /{id}/sessions` (force logout everywhere) ·
  `DELETE /{id}`
- Categories (`/api/v1/admin/categories`): `GET /` · `POST /` ·
  `PATCH /{id}` · `DELETE /{id}`
- Notifications (`/api/v1/admin/notifications`): `POST /broadcast` ·
  `GET /delivery-logs`
- Email (`/api/v1/admin/email`): `GET /config` (backend/sender, secrets
  redacted) · `POST /send` (send a custom email directly to one or more
  specific users, bypassing notification preferences)
- Stats (`/api/v1/admin/stats`): `GET /overview` — system-wide counts across
  users, expenses, categories, and notifications

Import `postman/Spenza.postman_collection.json` or open `bruno/` in Bruno to
try every endpoint — both include example request bodies and a `baseUrl`
variable.

## Testing

```bash
make test-cov
```

Tests run against an isolated in-memory SQLite database per test (no Postgres
required) with a fake email backend that captures OTPs for assertions. Current
coverage: **~93%** (gate is 90%, configured in `pyproject.toml`).

## Security Notes

- Passwords hashed with Argon2id; OTPs and refresh tokens hashed (SHA-256,
  appropriate since both are high-entropy, single-use, server-generated
  values, not user-chosen secrets).
- Account lockout after `LOGIN_MAX_FAILED_ATTEMPTS` failed logins; OTPs locked
  after `OTP_MAX_ATTEMPTS` wrong guesses.
- Rate limiting (`slowapi`) on signup/login/OTP endpoints.
- `TrustedHostMiddleware`, security response headers, per-request ID.
- Never logs passwords, OTPs, or raw tokens — only hashes/IDs/booleans.

## OTP housekeeping

An OTP row is only deleted automatically as a side effect of two flows: a
signup OTP the moment it's verified, and a password-reset OTP once
`reset-password` completes. Anything else — never verified, expired, or a
verified reset OTP whose owner never finished resetting — sits in
`email_otps` forever otherwise. Rows older than `2 × OTP_EXPIRE_MINUTES`
are considered safe to delete (see `cleanup_expired_otps` in
`src/modules/users/service.py` for why the window is doubled).

Two independent mechanisms handle this, deliberately overlapping:

- **In-app weekly task** (`src/lifespan.py`) — every running process sweeps
  automatically every 7 days, no setup needed. Caveat: it's a plain
  `asyncio.sleep` timer that resets on every restart, so if the process
  redeploys more often than weekly, this may rarely fire in practice.
- **External scheduler** (`make cleanup-otps` / `scripts/cleanup_otps.py`) —
  doesn't depend on process uptime. Wire it into cron, a systemd timer, or
  your hosting provider's scheduled-job feature, e.g.:

```bash
0 3 * * 0 cd /path/to/spenza && make cleanup-otps >> /var/log/spenza-otp-cleanup.log 2>&1
```

## Notes on local dev database

The default `DATABASE_URL` in `.env.example` points at a plain local Postgres
container. If you're sharing a Postgres instance with other local projects,
use a **dedicated database** for Spenza (e.g. `spenza` or `spenza_dev`) —
Alembic's autogenerate diff is schema-wide and will flag unrelated tables in
a shared database as "should be dropped." The checked-in migration only
touches Spenza's own tables (`users`, `refresh_sessions`, `email_otps`); review
any autogenerated migration before applying it if the database is shared.
