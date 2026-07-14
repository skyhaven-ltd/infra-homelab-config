"""products.txt parsing, URL->retailer resolution, and fetch escalation."""

import httpx

from config import load_products
from retailers import resolve_retailer
from retailers.base import BaseRetailer, StockResult


def test_load_products_parses_urls_names_comments(tmp_path):
    f = tmp_path / "products.txt"
    f.write_text(
        "# comment\n"
        "\n"
        "https://www.currys.co.uk/products/thing-123456\n"
        "https://shop.example.com/widget | My Widget\n"
        "not a url\n"
    )
    products = load_products(f)
    assert [p.url for p in products] == [
        "https://www.currys.co.uk/products/thing-123456",
        "https://shop.example.com/widget",
    ]
    assert products[0].name is None
    assert products[1].name == "My Widget"


def test_resolve_known_domains():
    cases = {
        "https://www.currys.co.uk/products/x-123": "currys",
        "https://www.amazon.co.uk/dp/B0ABC": "amazon",
        "https://ao.com/product/x": "ao",
        "https://www.argos.co.uk/product/1234": "argos",
        "https://www.screwfix.com/p/x": "screwfix",
        "https://www.diy.com/departments/x": "bq",
    }
    for url, key in cases.items():
        assert resolve_retailer(url).key == key, url


def test_unknown_domain_falls_back_to_generic():
    assert resolve_retailer("https://shop.example.com/widget").key == "generic"


def _retailer(fetches):
    """BaseRetailer whose fetch strategies are stubbed by name."""
    r = BaseRetailer(
        httpx.Client(), timeout=5.0, user_agent="test",
        flaresolverr_url="http://fs/v1",
    )
    r._fetch_static = fetches.get("static", _raise)
    r._fetch_flaresolverr = fetches.get("flaresolverr", _raise)
    r._fetch_rendered = fetches.get("playwright", _raise)
    return r


def _raise(url):
    raise RuntimeError("unavailable")


IN_STOCK_HTML = "<html><body><button>Add to basket</button></body></html>"
CHALLENGE_HTML = "<html><head><title>Just a moment...</title></head></html>"


def test_blocked_page_is_never_a_stock_verdict():
    BaseRetailer._preferred_strategy.clear()
    r = _retailer({"static": lambda url: (CHALLENGE_HTML, 200)})
    result = r.check("https://shop.example.com/x")
    assert result.in_stock is None


def test_escalates_from_blocked_static_to_flaresolverr():
    BaseRetailer._preferred_strategy.clear()
    r = _retailer({
        "static": lambda url: ("denied", 403),
        "flaresolverr": lambda url: (IN_STOCK_HTML, 200),
    })
    result = r.check("https://shop.example.com/x")
    assert result.in_stock is True


def test_successful_strategy_is_remembered_per_host():
    BaseRetailer._preferred_strategy.clear()
    calls = []

    def static(url):
        calls.append("static")
        return ("denied", 403)

    def fs(url):
        calls.append("flaresolverr")
        return (IN_STOCK_HTML, 200)

    r = _retailer({"static": static, "flaresolverr": fs})
    r.check("https://shop.example.com/x")
    r.check("https://shop.example.com/x")
    # Second check goes straight to flaresolverr — no repeated static attempt.
    assert calls == ["static", "flaresolverr", "flaresolverr"]


def test_all_strategies_fail_returns_undetermined_with_errors():
    BaseRetailer._preferred_strategy.clear()
    r = _retailer({})
    result = r.check("https://shop.example.com/x")
    assert result.in_stock is None
    assert "unavailable" in result.error
