"""Core check-and-compare logic.

For each configured product: resolve its retailer plugin from the URL, fetch
stock, persist the result, and fire notifications only on an Out-of-Stock ->
In-Stock transition. Undetermined checks (network errors, blocked pages,
unparseable layouts) update the timestamp but never count as a transition, so
a blip cannot trigger a false alert nor mask a later genuine restock. A
product that stays undetermined for several consecutive cycles is surfaced as
a warning so silent monitoring gaps are visible in the logs.
"""

from __future__ import annotations

import logging
import time
from urllib.parse import urlsplit

import httpx

from config import AppConfig, ProductConfig
from database import Database
from notifier import Alert, Notifier
from retailers import get_retailer, resolve_retailer

log = logging.getLogger(__name__)

# After this many consecutive undetermined checks, warn that the product is
# effectively unmonitored (site layout changed, or every strategy is blocked).
_UNDETERMINED_WARN_THRESHOLD = 5


class StockChecker:
    def __init__(self, config: AppConfig, db: Database, notifier: Notifier,
                 client: httpx.Client):
        self.config = config
        self.db = db
        self.notifier = notifier
        self.client = client
        self._undetermined_streak: dict[str, int] = {}

    def check_all(self) -> None:
        log.info("check cycle start (%d product(s))", len(self.config.products))
        for product in self.config.products:
            try:
                self.check_one(product)
            except Exception as exc:  # never let one product kill the cycle
                log.exception("unhandled error checking %s: %s", product.url, exc)
        log.info("check cycle complete")

    def check_one(self, product: ProductConfig) -> None:
        retailer_cls = (
            get_retailer(product.retailer) if product.retailer
            else resolve_retailer(product.url)
        )
        retailer = retailer_cls(
            self.client,
            timeout=self.config.request_timeout,
            user_agent=self.config.user_agent,
            flaresolverr_url=self.config.flaresolverr_url,
        )
        self.db.ensure(product.url, retailer_cls.key)
        previous = self.db.get(product.url)
        was_in_stock = bool(previous.in_stock) if previous else False

        started = time.monotonic()
        result = retailer.check(product.url)
        elapsed_ms = (time.monotonic() - started) * 1000

        name = product.name or result.name or (previous.name if previous else None)
        log.info(
            "checked retailer=%s status=%s stock=%s price=%s time=%.0fms url=%s%s",
            retailer_cls.key,
            result.status_code,
            result.in_stock,
            result.price,
            elapsed_ms,
            product.url,
            f" error={result.error}" if result.error else "",
        )

        if not result.determined:
            streak = self._undetermined_streak.get(product.url, 0) + 1
            self._undetermined_streak[product.url] = streak
            if streak == _UNDETERMINED_WARN_THRESHOLD:
                log.warning(
                    "%s has been undetermined for %d consecutive checks — "
                    "not currently monitored (last error: %s)",
                    product.url, streak, result.error,
                )
            # Keep last-known stock state; only refresh timestamp/price/name.
            self.db.update_state(
                product.url,
                name=name,
                in_stock=was_in_stock,
                price=result.price,
                alerted=False,
            )
            return

        self._undetermined_streak.pop(product.url, None)
        now_in_stock = bool(result.in_stock)
        transitioned = now_in_stock and not was_in_stock

        if transitioned:
            alert = Alert(
                retailer=_retailer_label(retailer_cls, product.url),
                name=name or product.url,
                url=product.url,
                price=result.price or (previous.price if previous else None),
            )
            self.notifier.send(alert)

        self.db.update_state(
            product.url,
            name=name,
            in_stock=now_in_stock,
            price=result.price,
            alerted=transitioned,
        )


def _retailer_label(retailer_cls, url: str) -> str:
    """Notification header: plugin display name, or the site's hostname when
    the generic fallback handled the URL."""
    if retailer_cls.key == "generic":
        host = (urlsplit(url).hostname or "").lower()
        return host.removeprefix("www.") or retailer_cls.display_name
    return retailer_cls.display_name
