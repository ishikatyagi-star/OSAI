from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import health, integrations, search, sync_runs, workflows
from config import settings

app = FastAPI(title="OSAI API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(integrations.router)
app.include_router(sync_runs.router)
app.include_router(search.router)
app.include_router(workflows.router)
