from workers.celery_app import celery_app


@celery_app.task
def extract_action_items(workflow_run_id: str) -> dict[str, str]:
    return {"workflow_run_id": workflow_run_id, "status": "queued"}
