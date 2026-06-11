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
- **Services**: Postgres, Qdrant, Redis — use managed instances (Render
  Postgres, Qdrant Cloud free tier, Upstash Redis) or self-host via
  `docker-compose.yml`.

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
| `NEXT_PUBLIC_DEMO_MODE` | `false` | No (defaults to demo) |

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
git submodule update --init --recursive

cp osai-backend/.env.example osai-backend/.env
# Edit .env with real keys (Gemini, connectors, Composio, DB URL)

docker compose up -d
```

This brings up: API (port 8000), Celery worker, Postgres (5433→5432),
Qdrant (6333), Redis (6379), and gbrain (4000) — all in one stack.

### Option B: Render / Railway

1. Create a new **Web Service** pointing to `osai-backend/`.
2. Set the build command: `pip install uv && uv sync`.
3. Set the start command: `uv run uvicorn api.main:app --host 0.0.0.0 --port $PORT`.
4. Add a **Background Worker** for Celery: `uv run celery -A workers.celery_app worker --loglevel=info`.
5. Provision managed **Postgres** + **Redis** from the platform.
6. For Qdrant: use [Qdrant Cloud](https://cloud.qdrant.io) free tier (1GB).
7. Set all env vars from `osai-backend/.env.example`.

### Option C: Fly.io

Use the existing `osai-backend/Dockerfile`:
```bash
cd osai-backend
fly launch --dockerfile Dockerfile
fly secrets set OSAI_GEMINI_API_KEY=... OSAI_DATABASE_URL=... # etc.
```

---

## Post-deploy checklist

- [ ] `GET https://api.osai.dev/health` returns 200
- [ ] Frontend loads at `https://app.osai.dev` and shows the dashboard
- [ ] Ask OSAI page works (demo fallback if backend not yet live)
- [ ] At least one connector syncs successfully
- [ ] A workflow can be triggered and an action item approved

---

## Environment variable reference

### Frontend (`osai-web/.env.local`)
See `osai-web/.env.example`.

### Backend (`osai-backend/.env`)
See `osai-backend/.env.example` + the additions documented in
`OSAI_EXECUTION_PLAN.md` §4.4.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Frontend shows only demo data | Check `NEXT_PUBLIC_API_BASE_URL` points to a running backend |
| "Cannot connect to database" | Port mismatch — see `OSAI_EXECUTION_PLAN.md` §4.2 |
| CORS errors in browser | Add your frontend URL to `OSAI_ALLOWED_ORIGINS` in backend `.env` |
| Vercel build fails | Ensure Root Directory is set to `osai-web` |
| gbrain container won't start | Run `git submodule update --init --recursive` first |
