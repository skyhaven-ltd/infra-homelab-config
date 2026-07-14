"""Transition logic: alert only on OOS -> IS, dedupe, undetermined handling."""

import httpx

from checker import StockChecker
from config import AppConfig, ProductConfig
from database import Database
from notifier import Notifier
from retailers import StockResult, get_retailer, register
from retailers.base import BaseRetailer


class _FakeNotifier(Notifier):
    def __init__(self):
        self.alerts = []
        self.channels = []

    def send(self, alert):
        self.alerts.append(alert)


# A controllable retailer whose next result is set by the test.
@register("_test")
class _TestRetailer(BaseRetailer):
    display_name = "TestShop"
    next_result = StockResult(in_stock=None)

    def check(self, url, *, force_playwright=None):
        return type(self).next_result


def _build(tmp_path):
    config = AppConfig(
        database_path=str(tmp_path / "t.db"),
        products=[ProductConfig(retailer="_test", url="http://x/p")],
    )
    db = Database(config.database_path)
    notifier = _FakeNotifier()
    checker = StockChecker(config, db, notifier, httpx.Client())
    return checker, db, notifier


def _set(result):
    get_retailer("_test").next_result = result


def test_alert_on_transition_to_in_stock(tmp_path):
    checker, db, notifier = _build(tmp_path)

    _set(StockResult(in_stock=False, name="Aircon", price="£329"))
    checker.check_all()
    assert notifier.alerts == []
    assert db.get("http://x/p").in_stock is False

    _set(StockResult(in_stock=True, name="Aircon", price="£329"))
    checker.check_all()
    assert len(notifier.alerts) == 1
    assert notifier.alerts[0].price == "£329"


def test_no_duplicate_alert_while_still_in_stock(tmp_path):
    checker, _, notifier = _build(tmp_path)
    _set(StockResult(in_stock=False))
    checker.check_all()
    _set(StockResult(in_stock=True))
    checker.check_all()
    checker.check_all()  # still in stock -> no second alert
    assert len(notifier.alerts) == 1


def test_undetermined_preserves_state_and_no_alert(tmp_path):
    checker, db, notifier = _build(tmp_path)
    _set(StockResult(in_stock=True))
    checker.check_all()
    assert len(notifier.alerts) == 1

    _set(StockResult(in_stock=None, error="timeout"))
    checker.check_all()
    # State preserved as in-stock; no spurious alert on recovery.
    assert db.get("http://x/p").in_stock is True
    assert len(notifier.alerts) == 1


def test_re_alert_after_going_out_and_back(tmp_path):
    checker, _, notifier = _build(tmp_path)
    _set(StockResult(in_stock=False))
    checker.check_all()
    _set(StockResult(in_stock=True))
    checker.check_all()
    _set(StockResult(in_stock=False))
    checker.check_all()
    _set(StockResult(in_stock=True))
    checker.check_all()
    assert len(notifier.alerts) == 2
