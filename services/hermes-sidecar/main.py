"""OSAI ↔ Hermes-agent sidecar.

Hermes Agent (github.com/NousResearch/hermes-agent) is a single-operator agent.
This HTTP service lets OSAI's multi-tenant backend use it **per user** without
sharing data across tenants:

- every request runs in a per-user HERMES_HOME (isolated memory/skills);
- OSAI has already injected the user's *permitted* org context into the prompt
  and enforces the permission boundary on its side — Hermes only sees allowed text;
- one-shot, scriptable runs via `hermes -z` (final response text only).

Run:  uvicorn main:app --host 0.0.0.0 --port 8088
"""

from __future__ import annotations

import hmac
import os
import re
import subprocess

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

app = FastAPI(title="OSAI Hermes Sidecar")

# Shared secret with the OSAI API (this service is publicly reachable). Every
# /run must carry it as X-Sidecar-Token; OSAI sends it via
# OSAI_HERMES_SIDECAR_TOKEN. Fail closed: a missing secret must not silently
# turn into an unauthenticated public /run (that runs on our Groq quota).
# Explicit local-dev-only opt-out: SIDECAR_ALLOW_UNAUTHENTICATED_RUN=1.
AUTH_TOKEN = os.environ.get("SIDECAR_AUTH_TOKEN")
_ALLOW_UNAUTH = os.environ.get("SIDECAR_ALLOW_UNAUTHENTICATED_RUN") == "1"
if not AUTH_TOKEN and not _ALLOW_UNAUTH:
    raise RuntimeError(
        "SIDECAR_AUTH_TOKEN is required. Set SIDECAR_ALLOW_UNAUTHENTICATED_RUN=1 "
        "to explicitly run without auth (local dev only)."
    )

# org_id/user_id become filesystem path segments — restrict them so a crafted
# id can't escape HERMES_HOME_ROOT (path traversal).
_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")

HERMES_CMD = os.environ.get("HERMES_CMD", "hermes")
HERMES_HOME_ROOT = os.environ.get("HERMES_HOME_ROOT", "/data/hermes")
HERMES_MODEL = os.environ.get("HERMES_MODEL")  # e.g. "llama-3.3-70b-versatile"
HERMES_PROVIDER = os.environ.get("HERMES_PROVIDER")  # e.g. "openrouter", "groq"
# For providers not in hermes' built-in registry (e.g. Groq): any
# OpenAI-compatible endpoint, registered per-user as a custom provider.
HERMES_BASE_URL = os.environ.get("HERMES_BASE_URL")  # e.g. https://api.groq.com/openai/v1
# Cap completion tokens — providers like Groq reject hermes' default as too high.
HERMES_MAX_TOKENS = os.environ.get("HERMES_MAX_TOKENS")
# Keep the tool schema small: full hermes toolsets overflow strict request-size
# limits (Groq returns 413). OSAI injects context and owns actions, so the
# sidecar only needs a minimal set. Comma-separated hermes toolset names.
HERMES_TOOLSETS = os.environ.get("HERMES_TOOLSETS", "search")
# Provider credentials to seed into each per-user HERMES_HOME/.env (the agent
# reads keys from there). Provide whatever your chosen provider needs.
PROVIDER_ENV_KEYS = (
    "OPENROUTER_API_KEY",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GROQ_API_KEY",
    "GOOGLE_API_KEY",
)
# Which env key each HERMES_PROVIDER value's credentials live in — used to seed
# the per-user config.yaml's custom_providers.key_env. Must match HERMES_PROVIDER,
# not just "whichever key happens to be set" (a dev with both GROQ_API_KEY and
# OPENAI_API_KEY in their env would otherwise get the wrong one wired up).
PROVIDER_KEY_ENV = {
    "openrouter": "OPENROUTER_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "groq": "GROQ_API_KEY",
    "gemini": "GOOGLE_API_KEY",
}
RUN_TIMEOUT = int(os.environ.get("HERMES_RUN_TIMEOUT", "180"))


class RunRequest(BaseModel):
    prompt: str
    org_id: str
    user_id: str | None = None
    permissions: list[str] = []


def _safe_segment(value: str) -> str:
    if value in {".", ".."} or not _SAFE_SEGMENT.match(value):
        raise HTTPException(status_code=400, detail="invalid org_id/user_id")
    return value


def _ensure_home(org_id: str, user_id: str | None) -> str:
    """Per-user home dir with provider keys (.env) + model config (config.yaml)."""
    home = os.path.join(
        HERMES_HOME_ROOT, _safe_segment(org_id), _safe_segment(user_id or "_org")
    )
    os.makedirs(home, exist_ok=True)
    env_path = os.path.join(home, ".env")
    if not os.path.exists(env_path):
        lines = [f"{k}={os.environ[k]}" for k in PROVIDER_ENV_KEYS if os.environ.get(k)]
        if lines:
            with open(env_path, "w") as fh:
                fh.write("\n".join(lines) + "\n")
    cfg_path = os.path.join(home, "config.yaml")
    if HERMES_MODEL:
        lines = []
        if HERMES_BASE_URL and HERMES_PROVIDER:
            key_env = PROVIDER_KEY_ENV.get(HERMES_PROVIDER, "")
            lines += [
                "custom_providers:",
                f"  - name: {HERMES_PROVIDER}",
                f"    base_url: {HERMES_BASE_URL}",
                f"    key_env: {key_env}",
                f"    default_model: {HERMES_MODEL}",
            ]
        lines += ["model:"]
        if HERMES_PROVIDER:
            lines.append(f"  provider: {HERMES_PROVIDER}")
        lines.append(f"  model: {HERMES_MODEL}")
        if HERMES_MAX_TOKENS:
            lines.append(f"  max_tokens: {HERMES_MAX_TOKENS}")
        desired_cfg = "\n".join(lines) + "\n"
        # Rewrite only on change — this is the whole file (not user-editable),
        # so a diff means the env-driven settings changed since it was last
        # written; a redeploy/key rotation shouldn't leave stale per-user config
        # (e.g. a since-lowered HERMES_MAX_TOKENS) on the persistent disk.
        current_cfg = ""
        if os.path.exists(cfg_path):
            with open(cfg_path) as fh:
                current_cfg = fh.read()
        if current_cfg != desired_cfg:
            with open(cfg_path, "w") as fh:
                fh.write(desired_cfg)
    return home


@app.get("/health")
def health() -> dict:
    return {"ok": True, "hermes_cmd": HERMES_CMD, "model": HERMES_MODEL}


@app.post("/run")
def run(req: RunRequest, x_sidecar_token: str | None = Header(default=None)) -> dict:
    if AUTH_TOKEN and not hmac.compare_digest(x_sidecar_token or "", AUTH_TOKEN):
        raise HTTPException(status_code=401, detail="missing/invalid X-Sidecar-Token")
    home = _ensure_home(req.org_id, req.user_id)
    env = {**os.environ, "HERMES_HOME": home}
    # -z = single prompt in, final text out. Provider/model/max_tokens come from
    # the per-user config.yaml seeded by _ensure_home (custom providers like
    # Groq aren't addressable via -m/--provider flags).
    cmd = [HERMES_CMD, "-z", req.prompt]
    if HERMES_TOOLSETS:
        cmd += ["-t", HERMES_TOOLSETS]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=RUN_TIMEOUT, env=env
        )
    except FileNotFoundError:
        return {"result": None, "error": "hermes CLI not installed in this sidecar"}
    except subprocess.TimeoutExpired:
        return {"result": None, "error": "hermes run timed out"}
    if proc.returncode != 0:
        return {"result": None, "error": (proc.stderr or "")[-500:]}
    return {"result": proc.stdout.strip()}
