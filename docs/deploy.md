# OSAI Deployment Guide

## Architecture overview

```
┌─────────────────────┐       ┌─────────────────────────────────────────────┐
│   osai-web (Vercel) │──────▶│  osai-backend (Render / Railway / Fly / VM) │
│   Next.js 16        │ HTTPS │  FastAPI + Celery workers                   │
└─────────────────────┘       └──────────┬──────────────────────────────────┘
                                         │
                         ┌───────────────┼───────────────┐
                         ▼               ▼               ▼
                    PostgreSQL        Qdrant          Redis
                    (managed)        (managed)       (managed)
```

- **Frontend** (`osai-web/`): deployed on **Vercel** (zero-config for Next.js).
- **Backend** (`osai-backend/`): deployed on a host that supports Docker or
  Python + background workers (Render, Railway, Fly.io, or a VM with
  `docker compose up`).
- **Services**: PostgreSQL, Qdrant, and Redis — use Supabase/managed PostgreSQL,
  Qdrant Cloud, and managed Redis in hosted environments, or self-host the
  three datastores with `docker-compose.yml`.

---

## Frontend deployment (Vercel)

### 1. Connect the repo

1. Go to [vercel.com/new](https://vercel.com/new).
2. Import `ishikatyagi-star/OSAI` (or your fork).
3. Set **Root Directory** to `osai-web`.
4. Framework will auto-detect as **Next.js**.

### 2. Environment variables

Set in Vercel → Project → Settings → Environment Variables:

| Variable | Value | Required |
|---|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | `https://api.osai.dev` (your backend URL) | Yes |
| `NEXT_PUBLIC_OSAI_DEMO` | `1` for an intentional demo build; omit in production | No (disabled when omitted) |

### 3. Deploy

Push to `main` — Vercel auto-deploys. Preview deploys on every PR branch.

### 4. Custom domain (optional)

Add `app.osai.dev` in Vercel → Project → Domains.

---

## Backend deployment

### Option A: Docker Compose on a VM (simplest for pilot)

```bash
# On the VM (e.g. a $20/mo DigitalOcean droplet)
git clone https://github.com/ishikatyagi-star/OSAI.git
cd OSAI

cp osai-backend/.env.example osai-backend/.env
# Set OSAI_ENV=production, a strong JWT secret, Gemini, OAuth, and feature keys.
# Set OSAI_SQL_DSN_ENCRYPTION_KEYS before migrating if SQL sources already exist.

docker compose up -d
```

This runs a one-shot database migration, then starts the API (port 8000) and
Celery worker after Postgres, Redis, and Qdrant are healthy. Datastore ports are
published to loopback only: Postgres `127.0.0.1:5433`, Qdrant
`127.0.0.1:6333`, and Redis `127.0.0.1:6379`. gbrain is not a Compose service;
if you deliberately enable it, initialize the `services/gbrain` submodule and
brain directory on the host first.

### Option B: Render Blueprint / Railway

1. On Render, deploy the repository-root `render.yaml` as a Blueprint instead of
   recreating its services from manual commands.
   The Blueprint intentionally excludes the experimental Hermes sidecar and
   does not wire Hermes URL/token variables into the API or worker. Its
   shared-UID homes are namespace separation only; a future hosted design needs
   a private per-tenant container/UID/mount boundary (or equivalent reviewed
   isolation).
2. On Railway or another Docker host, deploy `osai-backend/Dockerfile`. Its API
   command migrates before serving; use a platform one-shot release/migration
   job before scaling the API to multiple instances.
3. Run one **Background Worker** for Celery: `uv run celery -A workers.celery_app worker -B -Q execute --loglevel=info`. The `execute` queue carries the scheduler heartbeat and recurring automation runs; `-B` runs the schedule. Keep this combined worker at one instance. Split beat into a separate single-instance service before scaling workers horizontally. Composio ingestion still runs as an API `BackgroundTask`; do not count this worker as ingest offload until a producer and real ingest task are implemented.
4. On Railway or another custom host, provision managed **Postgres** + **Redis**.
   The repository's Render Blueprint wires Key Value automatically and expects
   `OSAI_DATABASE_URL` to be a dashboard-managed Supabase secret on both API and
   worker. Its legacy Render Postgres declaration is not the runtime database.
5. For Qdrant, use [Qdrant Cloud](https://cloud.qdrant.io) or another managed instance.
6. Set the required deployment vars from `osai-backend/.env.example`; leave
   optional integration values unset until those features are enabled.

### Option C: Fly.io

Use the existing `osai-backend/Dockerfile`:
```bash
cd osai-backend
fly launch --dockerfile Dockerfile
fly secrets set OSAI_GEMINI_API_KEY=... OSAI_DATABASE_URL=... # etc.
```

---

## Post-deploy checklist

- [ ] `GET https://api.osai.dev/health/live` returns 200
- [ ] `/health/ready` returns 200 with `database`, `vector_store`, and `redis`
      checks healthy (the Redis check executes the Lua/EVAL path used by rate limiting)
- [ ] `/health` reports the deployed `build_sha` (`RENDER_GIT_COMMIT` on Render;
      set `OSAI_BUILD_SHA` on other hosts)
- [ ] Frontend loads at `https://app.osai.dev` and shows the dashboard
- [ ] Ask OSAI returns a live answer with the expected citations
- [ ] At least one connector syncs successfully
- [ ] A workflow can be triggered and an action item approved

The read-only production canary runs hourly and on demand via
`.github/workflows/production-canary.yml`. Override its targets with
repository variables `OSAI_CANARY_WEB_URL` and `OSAI_CANARY_API_URL`, or the
manual-run inputs. `OSAI_CANARY_EXPECTED_BUILD_SHA` can pin the expected backend
commit; scheduled runs otherwise require the workflow commit. The canary checks
the Sheldon landing content, login-page-specific content on a direct
non-redirecting login route, security headers, and the public auth config through
the frontend's same-origin `/api` proxy. It performs no sign-in or state-changing
requests.

An authenticated staging canary needs a resettable staging environment and
these GitHub Actions secrets/variables before it is safe to enable:

| Variable | Contract |
|---|---|
| `OSAI_CANARY_STAGING_WEB_URL` | Staging web origin, never production |
| `OSAI_CANARY_STAGING_API_URL` | Staging API origin, never production |
| `OSAI_CANARY_MEMBER_TOKEN` | Short-lived JWT for a disposable member account |
| `OSAI_CANARY_ADMIN_TOKEN` | Short-lived JWT for a disposable admin account |
| `OSAI_CANARY_RESET_URL` | Idempotent endpoint that restores only the canary org fixture |
| `OSAI_CANARY_RESET_TOKEN` | Secret accepted only by that staging reset endpoint |

Tokens can authenticate API requests with `Authorization: Bearer` and browser
tests through `POST /api/auth/session`. Do not add these secrets to the
read-only production workflow.

---

## Environment variable reference

### Frontend (`osai-web/.env.local`)
See `osai-web/.env.example`.

### Backend (`osai-backend/.env`)
For Slack Ask, set both `OSAI_SLACK_SIGNING_SECRET` and
`OSAI_SLACK_BOT_TOKEN`; token minting fails closed until both are present. SQL
sources must be public by default. To use an intentionally private peered/VPN
PostgreSQL host, list its exact hostname in `OSAI_SQL_SOURCE_HOST_ALLOWLIST`;
loopback, metadata addresses, and the app control database remain blocked.
Set `OSAI_SQL_DSN_ENCRYPTION_KEYS` before migration `0032` when any SQL source
exists, and before creating a new source. The first Fernet key encrypts new
values; retain older keys after it until every row has been rewrapped.

`osai-backend/.env.example` is the canonical variable inventory. Blank values
are placeholders only; keep secrets in the deployment platform, never in Git.

The app is the sole owner of rate-limit proxy trust, so every Uvicorn command
must retain `--no-proxy-headers`. `OSAI_RATE_LIMIT_FORWARDED_FOR_MODE` defaults
to `direct`; use `trusted_chain` only with explicit non-/0 proxy CIDRs. The
Render Blueprint selects `render_first`, matching Render's guarantee that the
first X-Forwarded-For entry is the client. IPv6 identities default to a `/64`
allocation (`32` through `128` are accepted), and the active Redis limiter-key
registry defaults to a hard cap of 10,000 via `OSAI_RATE_LIMIT_REDIS_MAX_KEYS`.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Frontend shows only demo data | Check `NEXT_PUBLIC_API_BASE_URL` points to a running backend |
| "Cannot connect to database" | Host-run backend uses Postgres `localhost:5433`; containers use `postgres:5432` |
| CORS errors in browser | Add your frontend URL to `OSAI_ALLOWED_ORIGINS` in backend `.env` |
| Vercel build fails | Ensure Root Directory is set to `osai-web` |
| gbrain is unavailable | Initialize `services/gbrain` and its brain directory on the host; it is not started by root Compose |
