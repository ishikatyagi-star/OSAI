# Hermes sidecar — deploy & validation runbook

Goal: stand up the Hermes sidecar, prove it actually runs, then point OSAI at it.
~15 minutes. OSAI stays on its in-house agent until the final step, so nothing
breaks while you do this.

> ⚠️ hermes-agent has **not** been run end-to-end from this repo. Treat steps 3–4
> as the real validation gate — only do step 5 (wire OSAI) after step 4 passes.

---

## 0. Pick a model provider + key

Hermes needs an LLM provider. Easiest is **OpenRouter** (one key, many models).
Get a key from openrouter.ai. You'll set:

- `OPENROUTER_API_KEY` = `sk-or-...`
- `HERMES_MODEL` = e.g. `anthropic/claude-sonnet-4`
- `HERMES_PROVIDER` = `openrouter`  *(confirm exact provider name via `hermes model`/docs)*

(Anthropic or OpenAI direct also work — set `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`
and the matching `HERMES_MODEL`/`HERMES_PROVIDER` instead.)

## 1. (Optional) validate locally first

```bash
cd services/hermes-sidecar
OPENROUTER_API_KEY=sk-or-... HERMES_MODEL=anthropic/claude-sonnet-4 HERMES_PROVIDER=openrouter \
  docker compose up --build
# in another shell:
curl -s localhost:8088/health
curl -s -X POST localhost:8088/run -H 'Content-Type: application/json' \
  -d '{"prompt":"Say hello in one sentence.","org_id":"test","user_id":"u1"}'
```
Expect `{"result":"<some text>"}`. If you get `{"result":null,"error":...}`, read
the error (usually: hermes install failed in the image, or the model/key is wrong).

## 2. Deploy on Render

Render Dashboard → **New → Web Service** → pick the OSAI repo, then:

| Setting | Value |
|---|---|
| Root directory | `services/hermes-sidecar` |
| Runtime | **Docker** (uses the Dockerfile here) |
| Health check path | `/health` |
| Instance | Starter or above (the build installs the hermes CLI) |

**Environment variables** (Environment tab):
```
OPENROUTER_API_KEY = sk-or-...
HERMES_MODEL       = anthropic/claude-sonnet-4
HERMES_PROVIDER    = openrouter
HERMES_HOME_ROOT   = /data/hermes
```
*(Optional)* add a **persistent disk** mounted at `/data/hermes` so each user's
Hermes memory survives restarts. Without it, per-user memory resets on redeploy —
fine for the pilot.

Deploy and note the service URL, e.g. `https://osai-hermes.onrender.com`.

## 3. Validate health

```bash
curl -s https://osai-hermes.onrender.com/health
# → {"ok": true, "hermes_cmd": "hermes", "model": "anthropic/claude-sonnet-4"}
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

**Do not proceed past here until you get a real `result`.**

## 5. Point OSAI at the sidecar

On the **osai-api** Render service → Environment, add:
```
OSAI_HERMES_SIDECAR_URL = https://osai-hermes.onrender.com
```
Save (redeploys). Now OSAI Automations route through per-user Hermes (with the
user's permission-scoped context injected by OSAI).

## 6. Validate end-to-end through OSAI

In the app: Automations → create one → **Run now**. Or via API with a real user
token. The run response carries a `via` field:
- `"via":"hermes"` → executed on Hermes ✅
- `"via":"osai"` → fell back to the in-house agent (sidecar unreachable/empty —
  recheck steps 3–5)

## Rollback (instant)

Unset `OSAI_HERMES_SIDECAR_URL` on osai-api and redeploy → everything returns to
the in-house agent. No data migration, no risk.

---

### Demo recommendation

Keep the demo on the in-house agent unless step 4 **and** step 6 both pass with
time to spare. Hermes is additive and rollback is one env var, so there's no
downside to enabling it only once it's proven.
