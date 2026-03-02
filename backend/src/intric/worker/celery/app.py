from __future__ import annotations

from celery import Celery

from intric.main.config import get_settings


def build_redis_url(database: int) -> str:
    settings = get_settings()
    return f"redis://{settings.redis_host}:{settings.redis_port}/{database}"


def create_celery_app(
    *,
    app_name: str,
    default_queue: str,
    task_routes: dict[str, dict[str, str]],
) -> Celery:
    settings = get_settings()
    app = Celery(app_name)
    app.conf.update(
        broker_url=build_redis_url(settings.redis_db_celery_broker),
        result_backend=build_redis_url(settings.redis_db_celery_result),
        task_default_queue=default_queue,
        task_routes=task_routes,
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        broker_transport_options={
            "visibility_timeout": settings.celery_visibility_timeout_seconds,
        },
        result_backend_transport_options={
            "visibility_timeout": settings.celery_visibility_timeout_seconds,
        },
        visibility_timeout=settings.celery_visibility_timeout_seconds,
    )
    return app
