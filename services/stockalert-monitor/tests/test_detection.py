"""Stock detection: JSON-LD, indicator phrases, and undetermined pages."""

import httpx
import pytest

from retailers import get_retailer, registered_keys

EXPECTED_RETAILERS = {
    "ao", "currys", "argos", "appliances_direct", "amazon",
    "very", "bq", "screwfix", "toolstation",
}


def make(key):
    cls = get_retailer(key)
    return cls(httpx.Client(), timeout=5.0, user_agent="test")


def parse(key, html):
    from bs4 import BeautifulSoup

    r = make(key)
    return r.parse_stock(BeautifulSoup(html, "lxml"), html)


def test_all_expected_retailers_registered():
    assert EXPECTED_RETAILERS.issubset(set(registered_keys()))


def test_jsonld_in_stock():
    html = """
    <html><head><script type="application/ld+json">
    {"@type":"Product","offers":{"@type":"Offer","availability":"https://schema.org/InStock"}}
    </script></head><body>Out of stock</body></html>
    """
    # JSON-LD wins over the misleading body text.
    assert parse("ao", html) is True


def test_jsonld_out_of_stock():
    html = """
    <script type="application/ld+json">
    {"@type":"Product","offers":{"availability":"OutOfStock"}}
    </script><body>Add to basket</body>
    """
    assert parse("argos", html) is False


def test_jsonld_graph_and_list_offers():
    html = """
    <script type="application/ld+json">
    {"@graph":[{"@type":"Product","offers":[{"availability":"https://schema.org/InStock"}]}]}
    </script>
    """
    assert parse("screwfix", html) is True


def test_positive_phrase_when_no_jsonld():
    assert parse("toolstation", "<body><button>Add to Basket</button></body>") is True


def test_negative_phrase_beats_positive():
    html = "<body>Out of Stock <button disabled>Add to Basket</button></body>"
    assert parse("bq", html) is False


def test_undetermined_page_returns_none():
    assert parse("ao", "<body>Some unrelated product blurb</body>") is None


def test_amazon_availability_block():
    in_stock = '<div id="availability"><span>In stock</span></div>'
    assert parse("amazon", in_stock) is True
    unavailable = '<div id="availability"><span>Currently unavailable.</span></div>'
    assert parse("amazon", unavailable) is False


def test_price_parsing():
    from bs4 import BeautifulSoup

    r = make("ao")
    soup = BeautifulSoup("<body>Now only £329.00 today</body>", "lxml")
    assert r.parse_price(soup) == "£329.00"


def test_unknown_retailer_raises():
    with pytest.raises(KeyError):
        get_retailer("nonexistent")
