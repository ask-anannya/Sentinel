"""
APScheduler wrapper for daily compliance scans.
"""

import logging
import os

from apscheduler.schedulers.background import BackgroundScheduler

import orchestrator

logger = logging.getLogger(__name__)

_scheduler = BackgroundScheduler()


def start_scheduler() -> None:
    """Start the background scheduler with a daily scan job."""
    interval_hours = int(os.environ.get("SCAN_INTERVAL_HOURS", "24"))

    _scheduler.add_job(
        orchestrator.run_scan,
        trigger="interval",
        hours=interval_hours,
        id="daily_compliance_scan",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info(
        "Scheduler started — compliance scan scheduled every %d hour(s)",
        interval_hours,
    )


def stop_scheduler() -> None:
    """Gracefully shut down the scheduler."""
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
