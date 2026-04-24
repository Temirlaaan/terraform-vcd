"""APScheduler setup for background jobs.

Started from FastAPI lifespan. Single process assumption — if we ever
run multiple replicas, add a Redis lock around job execution to prevent
duplicate fires (the drift_sync job already takes per-deployment locks,
so it is safe in practice, but a global lock would cut redundant VCD load).
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import settings

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


def _parse_cron(expr: str) -> CronTrigger:
    parts = expr.split()
    if len(parts) != 5:
        raise ValueError(f"Invalid cron expression: {expr!r}")
    minute, hour, day, month, dow = parts
    return CronTrigger(
        minute=minute,
        hour=hour,
        day=day,
        month=month,
        day_of_week=dow,
        timezone=settings.drift_sync_timezone,
    )


async def _drift_sync_wrapper() -> None:
    from app.jobs.drift_sync import sync_all_deployments
    try:
        await sync_all_deployments(triggered_by="cron")
    except Exception:
        logger.exception("drift_sync cron wrapper crashed")


def start_scheduler() -> AsyncIOScheduler | None:
    global _scheduler
    if not settings.drift_sync_enabled:
        logger.info("Scheduler disabled (DRIFT_SYNC_ENABLED=false)")
        return None
    if _scheduler is not None:
        return _scheduler

    scheduler = AsyncIOScheduler(timezone=settings.drift_sync_timezone)
    trigger = _parse_cron(settings.drift_sync_cron)
    scheduler.add_job(
        _drift_sync_wrapper,
        trigger=trigger,
        id="drift_sync_daily",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    _scheduler = scheduler
    logger.info(
        "Scheduler started: drift_sync cron=%r tz=%s",
        settings.drift_sync_cron, settings.drift_sync_timezone,
    )
    return scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("Scheduler stopped")
