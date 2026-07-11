from celery import Celery

from config import settings

celery_app = Celery(
    "osai",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "workers.tasks.ingest",
        "workers.tasks.extract",
        "workers.tasks.execute",
        "workers.tasks.automations",
    ],
)

celery_app.conf.task_routes = {
    "workers.tasks.ingest.*": {"queue": "ingest"},
    "workers.tasks.extract.*": {"queue": "extract"},
    "workers.tasks.execute.*": {"queue": "execute"},
    "workers.tasks.automations.*": {"queue": "execute"},
}

# Recurring schedule (requires beat — the worker runs with -B, see
# docker-compose.yml). The tick is deliberately finer than the shortest cadence
# (hourly) so due automations run within minutes of becoming due; the due check
# itself lives in db.repositories.list_due_automations.
celery_app.conf.beat_schedule = {
    "run-due-automations": {
        "task": "workers.tasks.automations.run_due_automations",
        "schedule": 300.0,  # every 5 minutes
    },
}
