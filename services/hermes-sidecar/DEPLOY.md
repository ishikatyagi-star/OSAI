# Hermes sidecar — local validation and production hold

## Current decision

This is an experimental local/trusted-monolith spike. **Do not deploy it as a
shared multi-tenant service.** It has been removed from `render.yaml`, and the
Render API/worker services no longer receive Hermes sidecar URL/token wiring.
Do not recreate the old public token-gated web service manually.

The blocker is architectural: org/user home paths all belong to the same OS UID
and every Hermes process has that identity. The paths separate names for
trusted testing; they do not stop one same-UID process from accessing another
home. Symlink rejection and private modes are defense in depth, not tenant
containment.

A future production design must use a private, non-public service and isolate
each tenant with an OS/container/mount boundary (or an equivalent boundary that
has been security reviewed). Only the target tenant's storage should be mounted
into its Hermes runtime.

## Historical validation

A July 2026 local Docker test returned a real Groq/Hermes answer and an OSAI
request reported `via: "hermes"`. That proves the experimental integration can
run; it does not prove production isolation, supply-chain reproducibility,
approved egress, lifecycle management, or safe multi-tenant concurrency.

## Local provider configuration

The tested Groq configuration was:

```text
GROQ_API_KEY      = gsk_...                              (secret)
HERMES_PROVIDER   = groq
HERMES_MODEL      = llama-3.3-70b-versatile
HERMES_BASE_URL   = https://api.groq.com/openai/v1
HERMES_MAX_TOKENS = 8192
HERMES_TOOLSETS   = search
SIDECAR_AUTH_TOKEN = <local random value>
```

Only the credential selected by `HERMES_PROVIDER` is persisted or passed to
Hermes. The sidecar will not start without `SIDECAR_AUTH_TOKEN`; there is no
unauthenticated development override.

`search` explicitly enables Hermes `web_search` and can send query text to an
external search provider. It is retained here only to reproduce the historical
test. It is a residual egress blocker, not a production recommendation.

## Local validation gate

Use trusted, non-sensitive data and keep the loopback-only Compose binding:

```bash
cd services/hermes-sidecar
GROQ_API_KEY=gsk_... HERMES_PROVIDER=groq \
HERMES_MODEL=llama-3.3-70b-versatile \
HERMES_BASE_URL=https://api.groq.com/openai/v1 HERMES_MAX_TOKENS=8192 \
HERMES_TOOLSETS=search SIDECAR_AUTH_TOKEN=local-test-token \
  docker compose up --build -d

curl -s http://127.0.0.1:8088/health/ready
# {"ok":true}

curl -s -X POST http://127.0.0.1:8088/run \
  -H 'Content-Type: application/json' \
  -H 'X-Sidecar-Token: local-test-token' \
  -d '{"prompt":"Say hello in one sentence.","org_id":"test","user_id":"u1"}'
```

Readiness is deliberately opaque. A `503` means at least one of these is not
ready: authentication, supported provider, selected provider credential, model,
Hermes CLI, or private writable/atomic storage. Inspect local logs and
configuration rather than returning secret/configuration detail to callers.

For a local OSAI process, set both:

```text
OSAI_HERMES_SIDECAR_URL=http://127.0.0.1:8088
OSAI_HERMES_SIDECAR_TOKEN=local-test-token
```

Unset both values to return to the in-house agent.

## Production exit criteria

Do not host or auto-wire this sidecar until all of the following are designed,
implemented, tested, and security reviewed:

1. A private-service topology with per-tenant container/UID/mount isolation.
2. An explicit tool-free profile or approved, enforced external-egress policy.
3. A deterministic Hermes install with pinned/digested base, apt, uv, Node, and
   locked dependencies; no unlocked installer fallback.
4. Blocking advisory/SBOM coverage for the installed Hermes environment, not
   only the wrapper's hash-locked requirements.
5. Tenant data deletion, retention, quota, backup/restore, and key-rotation
   lifecycle behavior.
6. Cross-instance concurrency, cancellation, timeout-descendant, capacity, and
   recovery tests.

The current Dockerfile verifies the upstream installer bytes and final Hermes
commit, but the installer still consumes mutable inputs and may fall back to an
unlocked dependency install. That remains explicitly unresolved in this bounded
hardening pass.
