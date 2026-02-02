"""Celery application configuration."""

from celery import Celery

from src.shared.config import get_settings

settings = get_settings()

celery_app = Celery(
    "monolathe",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "src.assetfactory.tasks",
        "src.postproduction.tasks",
        "src.distributor.tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Hong_Kong",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,  # 1 hour max
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=50,
)

    # Queue configuration
celery_app.conf.task_routes = {
    "src.assetfactory.*": {"queue": "mlx_inference_local"},
    "src.postproduction.*": {"queue": "video_render"},
    "src.distributor.*": {"queue": "upload"},
}

# Force Docker worker to pick up mlx_inference for testing
# (Normally this would run on Studio, but we want to test the Docker worker's logic)

