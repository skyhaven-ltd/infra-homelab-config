from __future__ import annotations

from bs4 import BeautifulSoup

from .base import BaseRetailer, StockResult, register


@register("amazon")
class AmazonRetailer(BaseRetailer):
    """Amazon UK.

    Amazon aggressively rate-limits/bot-detects; a headless browser is used and
    stock is read from the ``#availability`` block and the buy-box buttons.
    Expect occasional CAPTCHA pages (returned as an undetermined result).
    """

    display_name = "Amazon UK"
    domains = ["amazon.co.uk", "amazon.com"]
    use_playwright = True
    negative_indicators = BaseRetailer.negative_indicators + [
        "currently unavailable",
        "we don't know when or if this item will be back",
    ]

    def parse_name(self, soup: BeautifulSoup) -> str | None:
        tag = soup.select_one("#productTitle")
        if tag:
            return tag.get_text(strip=True)
        return super().parse_name(soup)

    def parse_price(self, soup: BeautifulSoup) -> str | None:
        whole = soup.select_one("span.a-price-whole")
        frac = soup.select_one("span.a-price-fraction")
        if whole:
            price = whole.get_text(strip=True).rstrip(".")
            if frac:
                price = f"{price}.{frac.get_text(strip=True)}"
            return f"£{price}"
        return super().parse_price(soup)

    def parse_stock(self, soup: BeautifulSoup, html: str) -> bool | None:
        avail = soup.select_one("#availability")
        if avail:
            text = avail.get_text(" ", strip=True).lower()
            if any(neg in text for neg in self.negative_indicators):
                return False
            if "in stock" in text:
                return True
        if soup.select_one("#add-to-cart-button, #buy-now-button"):
            return True
        return super().parse_stock(soup, html)
