from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import (
    agent,
    auth,
    health,
    integrations,
    orgs,
    search,
    settings,
    sync_runs,
    webhooks,
    workflow_actions,
    workflows,
)
from config import settings as app_settings

app = FastAPI(title="OSAI API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=app_settings.allowed_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(agent.router)
app.include_router(integrations.router)
app.include_router(sync_runs.router)
app.include_router(search.router)
app.include_router(workflows.router)
app.include_router(workflow_actions.router)
app.include_router(settings.router)
app.include_router(webhooks.router)
app.include_router(orgs.router)
app.include_router(auth.router)
