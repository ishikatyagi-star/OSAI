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
    ],
)

celery_app.conf.task_routes = {
    "workers.tasks.ingest.*": {"queue": "ingest"},
    "workers.tasks.extract.*": {"queue": "extract"},
    "workers.tasks.execute.*": {"queue": "execute"},
}
