import json
import logging
import time
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from api.routes import (
    agent,
    approval_policy,
    auth,
    automations,
    composio,
    decisions,
    dashboard,
    evals,
    graph,
    health,
    integrations,
    mcp,
    orgs,
    search,
    settings,
    sync_runs,
    team,
    webhooks,
    workflow_actions,
    workflows,
)
from config import settings as app_settings

app = FastAPI(title="OSAI API", version="0.1.0")
request_logger = logging.getLogger("osai.request")
app.add_middleware(
    CORSMiddleware,
    allow_origins=app_settings.allowed_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_request(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        request_logger.exception(
            json.dumps({"event": "request_failed", "request_id": request_id, "method": request.method, "path": request.url.path})
        )
        raise
    duration_ms = round((time.perf_counter() - started) * 1000)
    response.headers["X-Request-ID"] = request_id
    request_logger.info(
        json.dumps(
            {
                "event": "request_completed",
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            }
        )
    )
    return response

app.include_router(health.router)
app.include_router(agent.router)
app.include_router(approval_policy.router)
app.include_router(graph.router)
app.include_router(evals.router)
app.include_router(composio.router)
app.include_router(decisions.router)
app.include_router(mcp.router)
app.include_router(integrations.router)
app.include_router(sync_runs.router)
app.include_router(search.router)
app.include_router(workflows.router)
app.include_router(workflow_actions.router)
app.include_router(settings.router)
app.include_router(webhooks.router)
app.include_router(orgs.router)
app.include_router(auth.router)
app.include_router(team.router)
app.include_router(automations.router)
app.include_router(dashboard.router)
