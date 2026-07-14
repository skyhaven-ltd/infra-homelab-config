"""Retailer plugin architecture.

Retailers are resolved automatically from a product URL's hostname via
:func:`resolve_retailer`; any URL whose domain has no dedicated plugin falls
back to the generic detector in this base class, so arbitrary product pages
work without code changes.

The base implementation fetches with an escalating chain of strategies —
plain HTTP with real-browser headers, then FlareSolverr (solves Cloudflare
and similar bot walls in a real browser), then headless Playwright for pages
that only render stock client-side — and classifies stock from JSON-LD
``offers.availability`` or positive/negative indicator phrases. A strategy
that returns a blocked/challenge page is skipped, never misread as "out of
stock". The first strategy that yields a determined answer for a domain is
remembered and tried first on subsequent checks.

Retailers with a clean JSON API (e.g. Currys) override :meth:`check`
entirely; others override the class attributes (``domains``, indicator
phrases, ``use_playwright``/``use_flaresolverr``).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

# Registry: retailer key -> class.
_REGISTRY: dict[str, type["BaseRetailer"]] = {}


def register(key: str):
    def _wrap(cls: type["BaseRetailer"]) -> type["BaseRetailer"]:
        cls.key = key
        _REGISTRY[key] = cls
        return cls

    return _wrap


def get_retailer(key: str) -> type["BaseRetailer"]:
    try:
        return _REGISTRY[key]
    except KeyError:
        raise KeyError(
            f"Unknown retailer '{key}'. Registered: {sorted(_REGISTRY)}"
        ) from None


def registered_keys() -> list[str]:
    return sorted(_REGISTRY)


def resolve_retailer(url: str) -> type["BaseRetailer"]:
    """Pick the retailer class for a product URL by hostname suffix.

    ``www.currys.co.uk`` matches a plugin declaring ``domains = ["currys.co.uk"]``.
    Unmatched hostnames get the generic base detector.
    """
    host = (urlsplit(url).hostname or "").lower()
    for cls in _REGISTRY.values():
        for domain in cls.domains:
            if host == domain or host.endswith("." + domain):
                return cls
    return _REGISTRY.get("generic", BaseRetailer)


@dataclass
class StockResult:
    """Outcome of a single stock check.

    ``in_stock`` is ``None`` when the status could not be determined (network
    error, blocked page, unrecognised layout); callers must not treat ``None``
    as a transition.
    """

    in_stock: bool | None
    name: str | None = None
    price: str | None = None
    status_code: int | None = None
    error: str | None = None

    @property
    def determined(self) -> bool:
        return self.in_stock is not None


# Phrases that, if present in the page, indicate purchasable stock.
DEFAULT_POSITIVE = [
    "add to basket",
    "add to trolley",
    "add to cart",
    "buy now",
    "in stock",
    "available today",
    "add to bag",
]

# Phrases indicating no stock. Checked first — a page may contain both a
# disabled "add to basket" and an "out of stock" banner.
DEFAULT_NEGATIVE = [
    "out of stock",
    "sold out",
    "notify me",
    "email me when",
    "currently unavailable",
    "no longer available",
    "temporarily out of stock",
    "coming soon",
]

# Markers of bot-wall/challenge pages. Such pages must yield "blocked", never
# a stock verdict — a Cloudflare interstitial contains no product data.
_BLOCK_MARKERS = [
    "just a moment",
    "checking your browser",
    "verify you are human",
    "verifying you are human",
    "enable javascript and cookies to continue",
    "access denied",
    "pardon our interruption",
    "request unsuccessful",
    "captcha",
    "are you a robot",
]

_BLOCK_STATUSES = {403, 429, 503}

_PRICE_RE = re.compile(r"£\s?\d[\d,]*(?:\.\d{2})?")

# Real-browser headers for the plain-HTTP strategy. Many sites fingerprint on
# missing Accept/sec-ch headers long before they check the User-Agent.
_BROWSER_HEADERS = {
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
}


class _Blocked(Exception):
    """Fetched page is a bot-wall/challenge, not the product page."""


class BaseRetailer:
    key: str = "base"
    display_name: str = "Base"
    # Hostname suffixes this plugin claims (e.g. ["currys.co.uk"]).
    domains: list[str] = []
    # Start with Playwright for sites known to render stock client-side; start
    # with FlareSolverr for sites behind a bot wall. Either way the other
    # strategies remain as fallbacks.
    use_playwright: bool = False
    use_flaresolverr: bool = False
    positive_indicators: list[str] = DEFAULT_POSITIVE
    negative_indicators: list[str] = DEFAULT_NEGATIVE

    # Remembers, per hostname, the fetch strategy that last produced a
    # determined result so subsequent cycles skip strategies known to fail.
    _preferred_strategy: dict[str, str] = {}

    def __init__(
        self,
        client: httpx.Client,
        *,
        timeout: float,
        user_agent: str,
        flaresolverr_url: str | None = None,
    ):
        self.client = client
        self.timeout = timeout
        self.user_agent = user_agent
        self.flaresolverr_url = flaresolverr_url

    # -- Public API --------------------------------------------------------

    def check(self, url: str, *, force_playwright: bool | None = None) -> StockResult:
        host = (urlsplit(url).hostname or "").lower()
        strategies = self._strategy_order(host, force_playwright)

        best_undetermined: StockResult | None = None
        errors: list[str] = []

        for name, fetch in strategies:
            try:
                html, status = fetch(url)
                if (status in _BLOCK_STATUSES) or self._looks_blocked(html):
                    raise _Blocked(f"blocked/challenge page (status={status})")
                if status is not None and status >= 400:
                    # Error page, not the product page — never phrase-scan it.
                    raise _Blocked(f"HTTP {status}")
            except _Blocked as exc:
                errors.append(f"{name}: {exc}")
                log.debug("%s %s: %s — escalating", self.key, name, exc)
                continue
            except Exception as exc:  # network, timeout, browser launch
                errors.append(f"{name}: {exc}")
                log.debug("%s %s failed for %s: %s", self.key, name, url, exc)
                continue

            result = self._parse(html, status)
            if result.determined:
                type(self)._preferred_strategy[host] = name
                return result
            if best_undetermined is None:
                best_undetermined = result

        if best_undetermined is not None:
            best_undetermined.error = "stock signal not found in page"
            return best_undetermined
        return StockResult(
            in_stock=None, error="; ".join(errors) or "no fetch strategy available"
        )

    # -- Strategy selection --------------------------------------------------

    def _strategy_order(self, host: str, force_playwright: bool | None):
        available = {"static": self._fetch_static}
        if self.flaresolverr_url:
            available["flaresolverr"] = self._fetch_flaresolverr
        if _playwright_available():
            available["playwright"] = self._fetch_rendered

        if force_playwright or (self.use_playwright and force_playwright is None):
            order = ["playwright", "flaresolverr", "static"]
        elif self.use_flaresolverr:
            order = ["flaresolverr", "playwright", "static"]
        else:
            order = ["static", "flaresolverr", "playwright"]

        preferred = type(self)._preferred_strategy.get(host)
        if preferred in order:
            order.remove(preferred)
            order.insert(0, preferred)

        return [(n, available[n]) for n in order if n in available]

    # -- Fetching ----------------------------------------------------------

    def _fetch_static(self, url: str) -> tuple[str, int]:
        resp = self.client.get(
            url,
            timeout=self.timeout,
            follow_redirects=True,
            headers={"User-Agent": self.user_agent, **_BROWSER_HEADERS},
        )
        return resp.text, resp.status_code

    def _fetch_flaresolverr(self, url: str) -> tuple[str, int]:
        # FlareSolverr solves the Cloudflare/bot challenge in a real browser and
        # returns the final rendered HTML. Solves can take 10-40s, so allow a
        # generous timeout; the clearance cookie is reused for later same-domain
        # requests, making subsequent checks faster.
        resp = self.client.post(
            self.flaresolverr_url,
            json={"cmd": "request.get", "url": url, "maxTimeout": 60000},
            timeout=90.0,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != "ok":
            raise RuntimeError(f"flaresolverr: {data.get('message', 'unknown error')}")
        solution = data.get("solution", {})
        return solution.get("response", ""), solution.get("status")

    def _fetch_rendered(self, url: str) -> tuple[str, int]:
        # Imported lazily so the app runs without Playwright when no retailer needs it.
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page(user_agent=self.user_agent)
                resp = page.goto(url, wait_until="networkidle", timeout=self.timeout * 1000)
                html = page.content()
                status = resp.status if resp else 200
            finally:
                browser.close()
        return html, status

    # -- Parsing (override per retailer as needed) -------------------------

    def _parse(self, html: str, status: int | None) -> StockResult:
        soup = BeautifulSoup(html, "lxml")
        return StockResult(
            in_stock=self.parse_stock(soup, html),
            name=self.parse_name(soup),
            price=self.parse_price(soup),
            status_code=status,
        )

    def _looks_blocked(self, html: str) -> bool:
        if not html:
            return True
        # Challenge pages are small; only scan the head of large pages so a
        # marker phrase deep in e.g. product reviews cannot misfire.
        head = html[:100_000].lower()
        return any(marker in head for marker in _BLOCK_MARKERS)

    def parse_name(self, soup: BeautifulSoup) -> str | None:
        meta = soup.find("meta", property="og:title")
        if meta and meta.get("content"):
            return meta["content"].strip()
        if soup.title and soup.title.string:
            return soup.title.string.strip()
        h1 = soup.find("h1")
        return h1.get_text(strip=True) if h1 else None

    def parse_price(self, soup: BeautifulSoup) -> str | None:
        meta = soup.find("meta", property="product:price:amount")
        if meta and meta.get("content"):
            return f"£{meta['content'].strip()}"
        m = _PRICE_RE.search(soup.get_text(" ", strip=True))
        return m.group(0).replace(" ", "") if m else None

    def parse_stock(self, soup: BeautifulSoup, html: str) -> bool | None:
        # 1. Structured data is the most reliable signal when present.
        jsonld = self.parse_jsonld_availability(soup)
        if jsonld is not None:
            return jsonld
        # 2. Fall back to scanning visible text for indicator phrases.
        text = soup.get_text(" ", strip=True).lower()
        if any(neg in text for neg in self.negative_indicators):
            return False
        if any(pos in text for pos in self.positive_indicators):
            return True
        return None

    def parse_jsonld_availability(self, soup: BeautifulSoup) -> bool | None:
        """Read schema.org ``offers.availability`` from JSON-LD blocks."""
        for tag in soup.find_all("script", type="application/ld+json"):
            if not tag.string:
                continue
            try:
                data = json.loads(tag.string)
            except (ValueError, TypeError):
                continue
            for node in _iter_nodes(data):
                if not isinstance(node, dict):
                    continue
                offers = node.get("offers")
                for offer in _iter_nodes(offers):
                    if isinstance(offer, dict) and "availability" in offer:
                        avail = str(offer["availability"]).lower()
                        if "instock" in avail or "limitedavailability" in avail:
                            return True
                        if "outofstock" in avail or "soldout" in avail:
                            return False
        return None


def _playwright_available() -> bool:
    try:
        import playwright.sync_api  # noqa: F401
        return True
    except ImportError:
        return False


def _iter_nodes(data):
    """Yield dicts/values from arbitrarily nested JSON-LD (lists, @graph)."""
    if isinstance(data, list):
        for item in data:
            yield from _iter_nodes(item)
    elif isinstance(data, dict):
        yield data
        if "@graph" in data:
            yield from _iter_nodes(data["@graph"])
    else:
        yield data
