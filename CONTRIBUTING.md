# Contributing to OSAI

## Quick start

```bash
git clone https://github.com/ishikatyagi-star/OSAI.git
cd OSAI
git submodule update --init --recursive
```

**Frontend:**
```bash
cd osai-web
cp .env.example .env.local
npm install
npm run dev
```

**Backend:** follow [README.md](README.md#run-the-backend-locally); deployment-specific setup is in [docs/deploy.md](docs/deploy.md).

---

## Branch & PR workflow

Use short-lived branches and keep each pull request focused:

1. **Branch from main:** `git checkout main && git pull`
2. **Name your branch:** `be/<task>` (backend) or `fe/<task>` (frontend)
   - e.g. `be/p1-ask-endpoint`, `fe/p1-chat-ui`
3. **Stay in your lane:**
   - Backend → only touch `osai-backend/`, `docker-compose.yml`, and backend deployment config
   - Frontend → only touch `osai-web/`, `docs/design-system.md`, `evals/fixtures/`
   - If you must cross lanes, do it in a **separate tiny PR** and message the other person first.
4. **Commit often, PRs small** (1–2 days of work max).
5. **Before opening the PR:** `git fetch origin && git rebase origin/main`
6. **PR template:** fill out the checklist in `.github/pull_request_template.md`.
7. **Merge daily.** Long-lived branches cause conflicts; short ones don't.

---

## Code style

### Frontend (`osai-web/`)
- TypeScript strict mode
- shadcn/ui components (Tailwind v4) for new UI; existing CSS-class components are fine
- Use `cn()` from `lib/utils.ts` for conditional classes
- `npm run typecheck` must pass
- `npm run build` must pass (17+ routes, no errors)

### Backend (`osai-backend/`)
- Python 3.12, FastAPI, SQLAlchemy 2.0
- `uv` for deps, `ruff` for lint
- `uv run ruff check .` must pass
- `uv run pytest` must pass
- Never hardcode secrets; use `.env` variables

---

## Lane ownership

| Path | Owner |
|---|---|
| `osai-backend/` | Ishika (backend) |
| `osai-web/` | Co-founder (frontend) |
| `docker-compose.yml`, `render.yaml` | Ishika |
| `docs/api-contract.md` | Ishika writes, both review |
| `docs/design-system.md`, `docs/deploy.md` | Co-founder |
| `evals/fixtures/` | Co-founder (domain scenarios) |
| `evals/run_evals.py` | Ishika (wiring to real agent) |

---

## Contract-first development

The frontend and backend work in parallel via **contract-first** development:

1. Before building an endpoint, the backend commits the request/response shape to `docs/api-contract.md`.
2. The frontend builds against that shape using mock/demo data.
3. When the backend implementation lands, the frontend swaps mock → live (near-zero rework).

---

## Secrets

- **Never commit `.env` files or API keys.**
- Use `osai-backend/.env.example` and `osai-web/.env.example` as templates.
- The `.gitignore` already excludes `.env` and `.env.local`.

---

## Questions?

Open an issue or message in the team channel. When in doubt, check:
- [README.md](README.md) — local setup and current capability summary
- [docs/deploy.md](docs/deploy.md) — deployment configuration
- [docs/api-contract.md](docs/api-contract.md) — the shared API interface
