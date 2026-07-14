"""Currys retailer: parse the SFCC Product-Variation JSON (FlareSolverr-wrapped)."""

import httpx

from retailers import get_retailer


def _make(monkeypatch, product_json):
    """Build a Currys retailer whose FlareSolverr fetch returns product_json."""
    r = get_retailer("currys")(
        httpx.Client(), timeout=5.0, user_agent="test",
        flaresolverr_url="http://fs/v1",
    )
    wrapped = f"<html><body><pre>{product_json}</pre></body></html>"
    monkeypatch.setattr(r, "_fetch_flaresolverr", lambda url: (wrapped, 200))
    return r


IN = '{"product": {"productName": "DELONGHI EX100", "available": true, ' \
     '"price": {"sales": {"formatted": "\\u00a3949.00"}}}}'
OUT = '{"product": {"productName": "LOGIK LAC09C26 &amp; Dehumidifier", ' \
      '"available": false, "price": {"sales": {"formatted": "\\u00a3349.00"}}}}'


def test_currys_in_stock(monkeypatch):
    r = _make(monkeypatch, IN)
    res = r.check("https://www.currys.co.uk/products/delonghi-ex100-10300973")
    assert res.in_stock is True
    assert res.price == "£949.00"
    assert res.name == "DELONGHI EX100"


def test_currys_out_of_stock_and_unescape(monkeypatch):
    r = _make(monkeypatch, OUT)
    res = r.check("https://www.currys.co.uk/products/logik-lac09c26-white-10294164")
    assert res.in_stock is False
    assert res.price == "£349.00"
    assert "&" in res.name  # &amp; unescaped


def test_currys_no_pid_in_url(monkeypatch):
    r = _make(monkeypatch, IN)
    res = r.check("https://www.currys.co.uk/products/no-id-here")
    assert res.in_stock is None
    assert "product id" in (res.error or "")


def test_currys_pid_is_last_long_number(monkeypatch):
    # Slug contains short digit groups (lac09c26); pid must be the trailing SKU.
    captured = {}
    r = _make(monkeypatch, IN)

    def fake(url):
        captured["url"] = url
        return (f"<pre>{IN}</pre>", 200)

    monkeypatch.setattr(r, "_fetch_flaresolverr", fake)
    r.check("https://www.currys.co.uk/products/logik-lac09c26-white-10294164")
    assert "pid=10294164" in captured["url"]
