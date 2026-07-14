from __future__ import annotations

import html as htmllib
import json
import re

from bs4 import BeautifulSoup

from .base import BaseRetailer, StockResult, register

# Trailing long digit run in a product URL is the SKU/pid, e.g.
# .../logik-lac09c26-...-white-10294164 -> 10294164
_PID_RE = re.compile(r"(\d{5,})")


@register("currys")
class CurrysRetailer(BaseRetailer):
    """Currys (Salesforce Commerce Cloud).

    The product page renders stock client-side, and Cloudflare blocks direct
    automation. Instead we call the SFCC ``Product-Variation`` JSON controller
    through FlareSolverr (which carries the Cloudflare clearance), giving a
    clean ``available`` boolean, price, and name without HTML scraping.
    """

    display_name = "Currys"
    domains = ["currys.co.uk"]
    use_flaresolverr = True
    _API = (
        "https://www.currys.co.uk/on/demandware.store/"
        "Sites-curryspcworlduk-Site/en_GB/Product-Variation?pid={pid}"
    )

    def check(self, url: str, *, force_playwright: bool | None = None) -> StockResult:
        if not self.flaresolverr_url:
            return StockResult(in_stock=None, error="flaresolverr not configured")

        nums = _PID_RE.findall(url.split("?")[0])
        if not nums:
            return StockResult(in_stock=None, error="no product id in URL")
        pid = nums[-1]

        try:
            body, status = self._fetch_flaresolverr(self._API.format(pid=pid))
        except Exception as exc:
            return StockResult(in_stock=None, error=str(exc))

        # FlareSolverr wraps the JSON response in <html><body><pre>...</pre>.
        try:
            pre = BeautifulSoup(body, "lxml").find("pre")
            data = json.loads(pre.get_text() if pre else body)
        except (ValueError, AttributeError) as exc:
            return StockResult(in_stock=None, status_code=status, error=f"parse: {exc}")

        product = data.get("product") or {}
        available = product.get("available")
        name = product.get("productName")
        if name:
            name = htmllib.unescape(name)

        price = None
        sales = (product.get("price") or {}).get("sales") or {}
        if sales.get("formatted"):
            price = htmllib.unescape(sales["formatted"])

        in_stock = bool(available) if available is not None else None
        return StockResult(in_stock=in_stock, name=name, price=price, status_code=status)
