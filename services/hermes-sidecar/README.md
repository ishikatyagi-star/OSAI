# Hermes sidecar (experimental local spike)

This directory contains a thin HTTP wrapper around
[Hermes Agent](https://github.com/NousResearch/hermes-agent) for local,
trusted-monolith experiments.

> **Do not deploy this shared service for multi-tenant production.** The
> repository's `render.yaml` intentionally does not provision it or wire the
> API/worker to it.

## Security boundary

Each request uses an org/user-namespaced `HERMES_HOME`, but all homes and all
Hermes subprocesses run as the same OS UID. The directories are namespace
separation for trusted local testing, **not** a security boundary between
tenants. Modes `0700`/`0600`, atomic generated-file replacement, symlink
rejection, and per-home locking reduce accidental cross-talk; they cannot
contain a compromised same-UID process or eliminate filesystem races against
one.

The wrapper also:

- always requires `SIDECAR_AUTH_TOKEN` and timing-safe token comparison;
- validates filesystem path segments and rejects observed symlink components;
- writes and passes only the credential selected by `HERMES_PROVIDER`;
- gives Hermes a strict child environment that excludes the sidecar token,
  other provider keys, and unrelated platform secrets;
- serializes same-home subprocesses through a bounded 64-stripe lock pool while
  allowing different stripes to run concurrently; and
- returns stable failures without exposing provider/CLI stderr.

A production design needs a private, non-public service plus a real tenant
boundary: for example, a separate container/UID and mount namespace per tenant
with only that tenant's storage mounted. A bearer token and different home path
inside one shared UID are not equivalent.

## API

- `GET /health` returns liveness: `{ "ok": true }`.
- `GET /health/ready` returns only `{ "ok": boolean }`. Readiness requires the
  auth token, a supported provider, that provider's selected credential, a
  model, the Hermes CLI, and a successful private atomic storage probe.
- `POST /run` accepts `{ "prompt": str, "org_id": str, "user_id"?: str }` and
  requires `X-Sidecar-Token`.

Hermes runs as an argv list (`hermes -z <prompt> ...`), not through a shell.
Provider/model configuration is generated in the namespaced home. Only the
selected provider key is written to that home's `.env` and passed to the child.

## Dependency and image status

The wrapper's complete Python dependency graph is generated from
`requirements.in`, hash-locked in `requirements.txt`, installed with
`pip --require-hashes`, checked with `pip check`, and scanned by a blocking
current-advisory audit in sidecar CI.

That does **not** make the complete image reproducible. The Dockerfile verifies
the upstream installer bytes and final Hermes Git commit, but the pinned
installer still downloads mutable uv/Node inputs and can fall back from a
locked sync to unlocked installation. The Python base tag and apt packages also
float. The installer-created Hermes environment is not covered by the wrapper
requirements audit. Fix those supply-chain boundaries before considering a
hosted deployment.

## External egress

The configured `search` toolset is not inert: in the pinned Hermes source it
enables `web_search`, which can send query text to an external search backend.
OSAI's model/connector routing does not make that search egress approved. The
current spike retains `search` only to reproduce the tested request-size
configuration; an explicit tool-free Hermes profile and egress review are
prerequisites for hosting it.

## Run locally

Use only trusted, non-sensitive test data. Compose binds the service to
loopback and always requires an auth token.

```bash
cd services/hermes-sidecar
SIDECAR_AUTH_TOKEN=local-test-token \
GROQ_API_KEY=gsk_... \
HERMES_PROVIDER=groq \
HERMES_MODEL=llama-3.3-70b-versatile \
HERMES_BASE_URL=https://api.groq.com/openai/v1 \
HERMES_MAX_TOKENS=8192 \
  docker compose up --build
```

For a local OSAI process only:

```text
OSAI_HERMES_SIDECAR_URL=http://127.0.0.1:8088
OSAI_HERMES_SIDECAR_TOKEN=local-test-token
```

See [DEPLOY.md](DEPLOY.md) for the local validation gate and the production
architecture work that remains blocked.
