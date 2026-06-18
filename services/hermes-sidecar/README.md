# Hermes sidecar (spike)

A thin HTTP wrapper that lets OSAI's multi-tenant backend use
[Hermes Agent](https://github.com/NousResearch/hermes-agent) without giving up
per-org data isolation.

## Why a sidecar

Hermes Agent is designed as a **single-operator** agent (its own memory store,
skills, model routing; CLI-first). OSAI is a **multi-tenant SaaS**. Running one
shared Hermes across orgs risks leaking org A's memory/answers into org B. The
sidecar pattern keeps Hermes as a separate process and lets OSAI:

- pass the `org_id` explicitly on every call,
- isolate state with a **per-org `HERMES_HOME`** (separate memory/skills dir),
- keep auth, permissions, and tenant routing in OSAI (the boundary), not Hermes.

This mirrors how OSAI already runs gbrain/UltraContext as sidecars.

## API

- `GET /health` → `{ ok: true }`
- `POST /run` `{ "prompt": str, "org_id": str }` → `{ "result": str | null, "error"?: str }`

Hermes invocation is real: it runs `hermes -z "<prompt>"` (single prompt in,
final response text out) in a per-user `HERMES_HOME`, and seeds provider keys
into `$HERMES_HOME/.env`. Install uses the official script
(`curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash`).

## Run (Docker)

```bash
cd services/hermes-sidecar
OPENROUTER_API_KEY=sk-... HERMES_MODEL=anthropic/claude-sonnet-4 \
  docker compose up --build
```

Then point OSAI at it (Render env, or local):

```
OSAI_HERMES_SIDECAR_URL=http://localhost:8088   # or the deployed sidecar URL
```

When set, OSAI's **Automations** "Run now" runs via **per-user** Hermes
(`agent/hermes_client.py` → this `/run`): OSAI first injects the user's
permission-scoped org context into the prompt, then calls Hermes. If the sidecar
is unreachable/empty it **falls back to OSAI's in-house agent**. Unset = in-house
agent only (default).

## Permission model

OSAI is the boundary. It retrieves only what the requesting user is permitted to
see (`requester_permissions`) and injects that as context — Hermes never gets
broad access to the org store. Each user also gets an isolated `HERMES_HOME`.

## What still needs you (can't be done from the repo)

1. **Deploy this sidecar** (a Render service / any box with Docker) and set
   `OSAI_HERMES_SIDECAR_URL` on the OSAI backend.
2. **Provide a model provider + key** (`OPENROUTER_API_KEY` / `ANTHROPIC_API_KEY`
   / `OPENAI_API_KEY` + `HERMES_MODEL`).
3. **Validate end-to-end** once deployed (`GET /health`, then a test `/run`)
   before pointing the demo at it. hermes-agent has not been run end-to-end from
   the repo, so confirm the install + a real run on your box first.
4. **Scale/ops** later: per-user `HERMES_HOME` persists per user — decide storage
   and long-running-vs-per-task before scaling.

Feature-flagged off until `OSAI_HERMES_SIDECAR_URL` is set, so production is
unaffected until you deliberately enable it.
