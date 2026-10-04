import os

from celery import Celery

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "dag_engine",
    broker=REDIS_URL,
    backend=REDIS_URL,
)

celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    # Run by the beat service (docker-compose `beat`), executed by workers.
    # A tick that sat in the queue past the next one is dropped, not run late.
    beat_schedule={
        "sweep-wait-timeouts": {
            "task": "tasks.sweep_wait_timeouts",
            "schedule": 15.0,
            "options": {"expires": 14},
        },
        "fire-due-schedules": {
            "task": "tasks.fire_due_schedules",
            "schedule": 15.0,
            "options": {"expires": 14},
        },
    },
)

# Worker is started with `-A tasks` so that circular import is not needed here.
