"""APScheduler wrapper running the check cycle on a fixed interval."""

from __future__ import annotations

import logging

from apscheduler.schedulers.blocking import BlockingScheduler

from checker import StockChecker

log = logging.getLogger(__name__)


def run_scheduler(checker: StockChecker, interval_seconds: int) -> None:
    scheduler = BlockingScheduler(timezone="UTC")
    scheduler.add_job(
        checker.check_all,
        trigger="interval",
        seconds=interval_seconds,
        # If a cycle overruns the interval, coalesce and skip missed runs
        # rather than piling jobs up.
        max_instances=1,
        coalesce=True,
        id="stock-check",
    )
    log.info("scheduler started — checking every %ds", interval_seconds)
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("scheduler stopping")
        scheduler.shutdown(wait=False)
