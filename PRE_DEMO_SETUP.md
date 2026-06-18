# Pre-demo setup checklist

Everything left is **configuration** (Render/Vercel/Google dashboards) — no code.
`⬜` = still to do · `✅` = already done earlier.

## A. Render → `osai-api` service → Environment

| Var | Status | Value / how |
|---|---|---|
| `OSAI_JWT_SECRET` | ⬜ **do this** | A strong random string. Generate locally: `openssl rand -hex 32`. **Don't paste it anywhere shared.** Until set, a known dev default signs sessions → tokens are forgeable. Required before a real pilot. |
| `OSAI_OPENAI_API_KEY` | ⬜ optional | Your OpenAI key (`sk-...`). Enables Whisper transcription of Drive audio/video. Without it, media is indexed by filename only (no regression). |
| `OSAI_GOOGLE_OAUTH_CLIENT_ID` | ✅ | set |
| `OSAI_GOOGLE_OAUTH_CLIENT_SECRET` | ✅ | set (consider rotating — it was shared in chat) |
| `OSAI_GOOGLE_OAUTH_REDIRECT_URI` | ✅ | `https://osai-api-ema6.onrender.com/auth/google/callback` |
| `OSAI_FRONTEND_URL` | ✅ | `https://osai-five.vercel.app` |
| `OSAI_ALLOWED_ORIGINS` | ✅ | `https://osai-five.vercel.app` |
| `OSAI_PUBLIC_BASE_URL` | ✅ | `https://osai-api-ema6.onrender.com` |
| Qdrant / Gemini / LLM (Groq) / Composio keys | ✅ | set (existing) |
| `OSAI_HERMES_SIDECAR_URL` | ⬜ only when ready | Set **only after** the Hermes sidecar passes its validation gate — see `services/hermes-sidecar/DEPLOY.md`. Leave unset = in-house agent (the recommended demo path). |

After changing env vars, Render redeploys automatically.

## B. Vercel → frontend → Environment Variables

| Var | Status | Value |
|---|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | ✅ | `https://osai-api-ema6.onrender.com` (redeploy if changed) |

## C. Manual actions (in the app / Google console)

- ⬜ **Re-sign-in once.** The JWT switch invalidated old sessions; sign in again with Google (you + co-founder).
- ⬜ **Reconnect Notion.** Its Composio connection expired — Integrations → Notion → Connect → then Sync now.
- ⬜ **OAuth consent screen:** keep your Google account under **Test users** while the app is in Testing mode.
- ⬜ *(optional, post-demo)* **Celery worker** for recurring automations. "Run now" works without it; only cadence-based auto-runs need a worker service.

## D. Quick verification after A–C

```bash
API=https://osai-api-ema6.onrender.com
curl -s $API/auth/config                      # {"google_enabled":true}
curl -s -o /dev/null -w '%{http_code}\n' $API/integrations   # 401 (no token = enforced)
curl -s -o /dev/null -w '%{http_code}\n' -H 'X-Org-Id: demo-org' $API/integrations  # 200
```
Then in the app: sign in → Integrations shows one card per app → Notion reconnect +
Sync now pulls real pages → Analytics shows real counts → Automations “Run now” returns an answer.

## Priorities
1. `OSAI_JWT_SECRET` (security) + re-sign-in.
2. Reconnect Notion.
3. `OSAI_OPENAI_API_KEY` if you want media transcribed in the demo.
4. Hermes only if its validation gate passes with time to spare (`services/hermes-sidecar/DEPLOY.md`).
