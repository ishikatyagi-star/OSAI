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

## Run

```bash
cd services/hermes-sidecar
pip install fastapi "uvicorn[standard]"
# + install hermes-agent (see its README) so the `hermes` CLI is on PATH
uvicorn main:app --port 8088
```

Then point OSAI at it:

```
OSAI_HERMES_SIDECAR_URL=http://localhost:8088
```

When set, OSAI's **Automations** "Run now" executes via Hermes
(`agent/hermes_client.py` → this `/run`), falling back to OSAI's in-house agent
if the sidecar is unreachable. Unset = in-house agent only (default).

## Open items (what this spike surfaces)

1. **Confirm the real Hermes invocation.** `main.py` shells out to
   `hermes run --prompt …` as a placeholder — verify the actual CLI/Python API
   from hermes-agent and update it.
2. **Install step** in the Dockerfile is a TODO until #1 is confirmed.
3. **Model + tool credentials** for Hermes (OpenRouter/OpenAI/Anthropic keys,
   the toolkits it should use) must be provided to the sidecar's environment.
4. **Per-org cost/ops**: a per-org `HERMES_HOME` isolates state but persists per
   tenant — decide on storage/cleanup before scaling.

Until these are closed, treat this as a prototype: the OSAI side is
feature-flagged off (`OSAI_HERMES_SIDECAR_URL` unset), so nothing changes in
production until you deliberately enable it.
