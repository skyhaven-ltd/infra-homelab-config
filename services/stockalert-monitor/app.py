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
import threading

import httpx

from checker import StockChecker
from config import load_config
from database import Database
from logging_setup import setup_logging
from notifier import Notifier
from retailers import registered_keys
from scheduler import run_scheduler
from web import create_app


def build_checker(config_path: str):
    config = load_config(config_path)
    setup_logging(config.log_level, config.log_file)
    db = Database(config.database_path)
    client = httpx.Client(headers={"User-Agent": config.user_agent})
    notifier = Notifier(config.notifiers, client)
    checker = StockChecker(config, db, notifier, client)
    return config, checker, db


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Stock alert system with a database-backed product list"
    )
    parser.add_argument("--config", default="config.yaml", help="path to config.yaml")
    parser.add_argument(
        "--once", action="store_true", help="run one check cycle and exit"
    )
    parser.add_argument(
        "--list-retailers",
        action="store_true",
        help="print supported retailers and exit",
    )
    args = parser.parse_args()

    if args.list_retailers:
        print("\n".join(registered_keys()))
        return

    config, checker, db = build_checker(args.config)

    if args.once:
        checker.check_all()
        return

    def monitor() -> None:
        # Check immediately without delaying the management UI startup.
        checker.check_all()
        run_scheduler(checker, config.interval_seconds)

    scheduler_thread = threading.Thread(
        target=monitor,
        daemon=True,
        name="stock-check-scheduler",
    )
    scheduler_thread.start()

    from waitress import serve

    serve(create_app(db), host="0.0.0.0", port=8080, threads=4)


if __name__ == "__main__":
    main()
