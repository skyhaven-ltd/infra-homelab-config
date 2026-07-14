"""Entry point.

Loads config, wires up the database, notifier, HTTP client, and checker, runs
one immediate check on startup, then hands off to the scheduler.

Usage:
    python app.py                 # run scheduler
    python app.py --once          # single check cycle, then exit
    python app.py --list-retailers
    python app.py --config path/to/config.yaml
"""

from __future__ import annotations

import argparse
import logging
import sys

import httpx

from checker import StockChecker
from config import load_config
from database import Database
from logging_setup import setup_logging
from notifier import Notifier
from retailers import registered_keys, resolve_retailer
from scheduler import run_scheduler


def build_checker(config_path: str):
    config = load_config(config_path)
    setup_logging(config.log_level, config.log_file)
    log = logging.getLogger("app")

    if not config.products:
        log.error(
            "no products to monitor — add URLs (one per line) to %s",
            config.products_file,
        )
        sys.exit(2)
    for p in config.products:
        log.info("watching %s via '%s'", p.url, resolve_retailer(p.url).key)

    db = Database(config.database_path)
    client = httpx.Client(headers={"User-Agent": config.user_agent})
    notifier = Notifier(config.notifiers, client)
    checker = StockChecker(config, db, notifier, client)
    return config, checker


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Stock alert system — watches product URLs from products.txt"
    )
    parser.add_argument("--config", default="config.yaml", help="path to config.yaml")
    parser.add_argument("--once", action="store_true", help="run one check cycle and exit")
    parser.add_argument(
        "--list-retailers", action="store_true", help="print supported retailers and exit"
    )
    args = parser.parse_args()

    if args.list_retailers:
        print("\n".join(registered_keys()))
        return

    config, checker = build_checker(args.config)

    # Immediate check so a restock that happened while the app was down is
    # caught at startup rather than after the first interval.
    checker.check_all()

    if args.once:
        return

    run_scheduler(checker, config.interval_seconds)


if __name__ == "__main__":
    main()
