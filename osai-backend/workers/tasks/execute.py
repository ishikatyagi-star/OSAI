from workers.celery_app import celery_app


@celery_app.task
def execute_connector_action(action_id: str) -> dict[str, str]:
    return {"action_id": action_id, "status": "queued"}
