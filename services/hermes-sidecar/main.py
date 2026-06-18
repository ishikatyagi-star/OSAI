"""OSAI ↔ Hermes-agent sidecar (SPIKE).

Hermes Agent (github.com/NousResearch/hermes-agent) is a single-operator agent.
This thin HTTP service lets OSAI's multi-tenant backend call it per-org without
sharing data across tenants: every request runs in a per-org HERMES_HOME so
memory/skills are isolated. OSAI calls POST /run with {prompt, org_id} and
enforces auth/isolation on its side (see agent/hermes_client.py).

STATUS: prototype. The exact hermes invocation below (`HERMES_CMD run --prompt`)
must be confirmed against the installed hermes-agent CLI/Python API before this
is production-ready — that's the open item this spike surfaces.

Run:  uvicorn main:app --port 8088
"""

from __future__ import annotations

import os
import subprocess

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="OSAI Hermes Sidecar (spike)")

HERMES_CMD = os.environ.get("HERMES_CMD", "hermes")
HERMES_HOME_ROOT = os.environ.get("HERMES_HOME_ROOT", "/data/hermes")
RUN_TIMEOUT = int(os.environ.get("HERMES_RUN_TIMEOUT", "120"))


class RunRequest(BaseModel):
    prompt: str
    org_id: str
    user_id: str | None = None
    # The user's data-access scope. Enforcement of these on any retrieval Hermes
    # requests back into OSAI is OSAI's responsibility (the permission boundary).
    permissions: list[str] = []


@app.get("/health")
def health() -> dict:
    return {"ok": True, "hermes_cmd": HERMES_CMD}


@app.post("/run")
def run(req: RunRequest) -> dict:
    # Per-USER home (scoped under org) → each user's Hermes has its own isolated
    # memory/skills; nothing bleeds across users or tenants.
    leaf = req.user_id or "_org"
    home = os.path.join(HERMES_HOME_ROOT, req.org_id, leaf)
    os.makedirs(home, exist_ok=True)
    env = {**os.environ, "HERMES_HOME": home}
    try:
        proc = subprocess.run(
            [HERMES_CMD, "run", "--prompt", req.prompt],  # TODO: confirm real CLI
            capture_output=True,
            text=True,
            timeout=RUN_TIMEOUT,
            env=env,
        )
    except FileNotFoundError:
        return {"result": None, "error": "hermes CLI not installed in this sidecar"}
    except subprocess.TimeoutExpired:
        return {"result": None, "error": "hermes run timed out"}
    if proc.returncode != 0:
        return {"result": None, "error": (proc.stderr or "")[-500:]}
    return {"result": proc.stdout.strip()}
