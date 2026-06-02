from workers.celery_app import celery_app


@celery_app.task
def sync_connector(connector_key: str, org_id: str) -> dict[str, str]:
    return {"connector_key": connector_key, "org_id": org_id, "status": "queued"}
