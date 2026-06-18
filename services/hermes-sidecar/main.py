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

import os
import subprocess

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="OSAI Hermes Sidecar")

HERMES_CMD = os.environ.get("HERMES_CMD", "hermes")
HERMES_HOME_ROOT = os.environ.get("HERMES_HOME_ROOT", "/data/hermes")
HERMES_MODEL = os.environ.get("HERMES_MODEL")  # e.g. "anthropic/claude-sonnet-4"
HERMES_PROVIDER = os.environ.get("HERMES_PROVIDER")  # e.g. "openrouter"
# Provider credentials to seed into each per-user HERMES_HOME/.env (the agent
# reads keys from there). Provide whatever your chosen provider needs.
PROVIDER_ENV_KEYS = ("OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY")
RUN_TIMEOUT = int(os.environ.get("HERMES_RUN_TIMEOUT", "180"))


class RunRequest(BaseModel):
    prompt: str
    org_id: str
    user_id: str | None = None
    permissions: list[str] = []


def _ensure_home(org_id: str, user_id: str | None) -> str:
    """Per-user home dir with provider keys seeded into its .env."""
    home = os.path.join(HERMES_HOME_ROOT, org_id, user_id or "_org")
    os.makedirs(home, exist_ok=True)
    env_path = os.path.join(home, ".env")
    if not os.path.exists(env_path):
        lines = [f"{k}={os.environ[k]}" for k in PROVIDER_ENV_KEYS if os.environ.get(k)]
        if lines:
            with open(env_path, "w") as fh:
                fh.write("\n".join(lines) + "\n")
    return home


@app.get("/health")
def health() -> dict:
    return {"ok": True, "hermes_cmd": HERMES_CMD, "model": HERMES_MODEL}


@app.post("/run")
def run(req: RunRequest) -> dict:
    home = _ensure_home(req.org_id, req.user_id)
    env = {**os.environ, "HERMES_HOME": home}
    cmd = [HERMES_CMD, "-z", req.prompt]  # -z = single prompt in, final text out
    if HERMES_MODEL:
        cmd += ["-m", HERMES_MODEL]
    if HERMES_PROVIDER:
        cmd += ["--provider", HERMES_PROVIDER]
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
