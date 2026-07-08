# Hermes sidecar — deploy & validation runbook

Goal: stand up the Hermes sidecar, prove it actually runs, then point OSAI at it.
OSAI stays on its in-house agent until the final step, so nothing breaks while
you do this.

> ✅ **Validated end-to-end on Groq (July 2026):** local Docker build → `/health`
> → `/run` returns a real Hermes answer → OSAI `run_ask` returns `via: "hermes"`.
> The Groq settings below are the exact validated recipe.

---

## 0. Model provider

**Groq (validated, uses the same key as `OSAI_LLM_API_KEY`):**

```
GROQ_API_KEY      = gsk_...                              (secret)
HERMES_PROVIDER   = groq
HERMES_MODEL      = llama-3.3-70b-versatile
HERMES_BASE_URL   = https://api.groq.com/openai/v1
HERMES_MAX_TOKENS = 8192
HERMES_TOOLSETS   = search
```

Why the extra knobs: `groq` is not in hermes' built-in provider registry, so the
sidecar registers it as a *custom provider* (OpenAI-compatible `base_url`) in
each per-user `config.yaml`. Groq also rejects hermes' default completion cap
(`max_tokens` error) and 413s on the full hermes toolset schema — `8192` +
`search` fixes both. OSAI injects permission-scoped context and owns the
action layer, so the sidecar doesn't need hermes' tools anyway.

OpenRouter / Anthropic / OpenAI also work: set `OPENROUTER_API_KEY` /
`ANTHROPIC_API_KEY` / `OPENAI_API_KEY` + `HERMES_PROVIDER`/`HERMES_MODEL`
(no `HERMES_BASE_URL` needed — those are built-in providers).

## 1. (Optional) validate locally first

```bash
cd services/hermes-sidecar
GROQ_API_KEY=gsk_... HERMES_PROVIDER=groq HERMES_MODEL=llama-3.3-70b-versatile \
HERMES_BASE_URL=https://api.groq.com/openai/v1 HERMES_MAX_TOKENS=8192 \
  docker-compose up --build -d
# in another shell:
curl -s localhost:8088/health
curl -s -X POST localhost:8088/run -H 'Content-Type: application/json' \
  -d '{"prompt":"Say hello in one sentence.","org_id":"test","user_id":"u1"}'
```
Expect `{"result":"<some text>"}`. If you get `{"result":null,"error":...}`, read
the error (usually: hermes install failed in the image, or the model/key is wrong).

## 2. Deploy on Render (Blueprint)

The service is defined in the repo's `render.yaml` as **`osai-hermes`**
(Docker, root `services/hermes-sidecar`, health check `/health`, plan
**Starter** — the hermes CLI build needs it, ~$7/mo — plus a 1 GB disk at
`/data/hermes` so per-user memory survives deploys). Merging to `main` makes
the Blueprint provision it automatically.

One manual step: on the **osai-hermes** service → Environment, set
```
GROQ_API_KEY = gsk_...   (same value as osai-api's OSAI_LLM_API_KEY)
```
All other env vars are committed in `render.yaml`.

## 3. Validate health

```bash
curl -s https://osai-hermes.onrender.com/health
# → {"ok": true, "hermes_cmd": "hermes", "model": "llama-3.3-70b-versatile"}
```

## 4. Validate a real run (the gate)

```bash
curl -s -X POST https://osai-hermes.onrender.com/run \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"Summarise what you can do in one sentence.","org_id":"test","user_id":"u1"}'
```
- ✅ `{"result":"<real answer>"}` → Hermes works. Proceed.
- ❌ `{"result":null,"error":"hermes CLI not installed..."}` → the Docker build's
  install step failed; check build logs.
- ❌ `error` about model/provider/auth → fix the env vars in step 2.
- ❌ `result` contains an error *sentence* (e.g. "max_tokens exceeds...",
  "Request payload too large") → hermes ran but the provider rejected the
  request; check `HERMES_MAX_TOKENS` / `HERMES_TOOLSETS`.

**Do not proceed past here until you get a real `result`.**

## 5. Point OSAI at the sidecar

On the **osai-api** Render service → Environment, add:
```
OSAI_HERMES_SIDECAR_URL = https://osai-hermes.onrender.com
```
Save (redeploys). Now `/ask` **and** Automations route through per-user Hermes
(with the user's permission-scoped context injected by OSAI, citations and the
propose/confirm action layer still handled by OSAI).

## 6. Validate end-to-end through OSAI

Ask a question in the app, or hit `/ask` with a real user token. The response
carries a `via` field:
- `"via":"hermes"` → executed on Hermes ✅ (`model_route` is `"hermes"` too)
- `"via":"osai"` → fell back to the in-house agent (sidecar unreachable/empty —
  recheck steps 3–5; the API logs a warning on every silent fallback)

Automations runs report the same `via` field.

## Rollback (instant)

Unset `OSAI_HERMES_SIDECAR_URL` on osai-api and redeploy → everything returns to
the in-house agent. No data migration, no risk. (Suspend the osai-hermes
service too if you want to stop the Starter charge.)
