import logging
import os

from celery import Celery
from celery.schedules import crontab

logger = logging.getLogger(__name__)

redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery("competitor_search", broker=redis_url, backend=redis_url)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    worker_prefetch_multiplier=1,
)

COLLECTORS = {
    "google": "collectors.google_collector.GoogleCollector",
    "yandex": "collectors.yandex_collector.YandexCollector",
    "vk": "collectors.vk_collector.VKCollector",
    "telegram": "collectors.telegram_collector.TelegramCollector",
}


def _import_collector(class_path: str):
    module_path, class_name = class_path.rsplit(".", 1)
    import importlib

    module = importlib.import_module(module_path)
    return getattr(module, class_name)


@celery_app.task(name="run_collector")
def run_collector_task(collector_name: str) -> dict:
    import asyncio

    from collectors.base import make_session_factory

    session_factory = make_session_factory()
    names = list(COLLECTORS.keys()) if collector_name == "all" else [collector_name]

    results = {}
    export_once = collector_name == "all"
    for name in names:
        if name not in COLLECTORS:
            results[name] = {"error": f"Unknown collector: {name}"}
            continue
        try:
            cls = _import_collector(COLLECTORS[name])
            collector = cls(session_factory)
            count = asyncio.run(collector.run(auto_export=not export_once))
            results[name] = {"items_collected": count}
        except Exception as exc:
            logger.exception("Collector %s failed", name)
            results[name] = {"error": str(exc)}

    if export_once:
        from app.auto_export import auto_export_report

        path = asyncio.run(auto_export_report(trigger="collector:all"))
        if path:
            results["report_docx"] = str(path)

    return results


@celery_app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    from app.config import get_settings

    settings = get_settings()
    hours = max(1, settings.monitor_interval_hours)
    sender.add_periodic_task(
        crontab(minute=0, hour=f"*/{hours}"),
        run_collector_task.s("all"),
        name="scheduled-monitor",
    )
