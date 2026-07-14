"""Configuration loading and validation.

Settings and notifier channels live in ``config.yaml``; the products to watch
live in ``products.txt`` — one URL per line, optionally followed by
``| Friendly name``. Environment variables referenced as ``${VAR}`` inside
yaml string values are expanded, so secrets (ntfy/Telegram tokens) can be
injected by Docker without being committed.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml

log = logging.getLogger(__name__)

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _expand(value: Any) -> Any:
    """Recursively expand ``${ENV_VAR}`` references in strings."""
    if isinstance(value, str):
        return _ENV_PATTERN.sub(lambda m: os.environ.get(m.group(1), ""), value)
    if isinstance(value, list):
        return [_expand(v) for v in value]
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    return value


@dataclass
class ProductConfig:
    url: str
    # Overrides the name scraped from the page in notifications.
    name: str | None = None
    # Forces a specific retailer plugin key; None = resolve from the URL.
    retailer: str | None = None


def load_products(path: str | Path) -> list[ProductConfig]:
    """Parse the products file: one URL per line, ``# comment`` lines ignored,
    optional ``| Friendly name`` after the URL."""
    products: list[ProductConfig] = []
    for lineno, raw_line in enumerate(
        Path(path).read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        url, _, name = (part.strip() for part in line.partition("|"))
        if not urlsplit(url).scheme.startswith("http"):
            log.warning("%s:%d: skipping non-URL line: %s", path, lineno, line)
            continue
        products.append(ProductConfig(url=url, name=name or None))
    return products


@dataclass
class NtfyConfig:
    enabled: bool = False
    server: str = "https://ntfy.sh"
    topic: str = ""
    token: str | None = None
    priority: int = 5  # urgent
    tags: list[str] = field(default_factory=lambda: ["rotating_light"])


@dataclass
class TelegramConfig:
    enabled: bool = False
    bot_token: str = ""
    chat_id: str = ""


@dataclass
class NotifierConfig:
    ntfy: NtfyConfig = field(default_factory=NtfyConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)


@dataclass
class AppConfig:
    interval_seconds: int = 60
    request_timeout: float = 20.0
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    products_file: str = "products.txt"
    database_path: str = "data/stock.db"
    log_level: str = "INFO"
    log_file: str = "data/stock-alert.log"
    # Endpoint of the FlareSolverr sidecar for Cloudflare-walled retailers.
    flaresolverr_url: str = "http://flaresolverr:8191/v1"
    products: list[ProductConfig] = field(default_factory=list)
    notifiers: NotifierConfig = field(default_factory=NotifierConfig)


def load_config(path: str | Path = "config.yaml") -> AppConfig:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    raw = _expand(raw)

    if raw.get("products"):
        log.warning(
            "config.yaml 'products' section is no longer read — "
            "put URLs in the products file instead"
        )

    settings = raw.get("settings", {}) or {}

    # Products file path is resolved relative to the config file, so running
    # from another cwd still finds it.
    products_file = settings.get("products_file", "products.txt")
    products_path = Path(products_file)
    if not products_path.is_absolute():
        products_path = Path(path).resolve().parent / products_path
    products = load_products(products_path) if products_path.exists() else []

    notif_raw = raw.get("notifiers", {}) or {}
    notifiers = NotifierConfig(
        ntfy=NtfyConfig(**(notif_raw.get("ntfy") or {})),
        telegram=TelegramConfig(**(notif_raw.get("telegram") or {})),
    )

    return AppConfig(
        interval_seconds=int(settings.get("interval_seconds", 60)),
        request_timeout=float(settings.get("request_timeout", 20.0)),
        user_agent=settings.get("user_agent", AppConfig.user_agent),
        products_file=str(products_path),
        database_path=settings.get("database_path", "data/stock.db"),
        log_level=settings.get("log_level", "INFO"),
        log_file=settings.get("log_file", "data/stock-alert.log"),
        flaresolverr_url=settings.get("flaresolverr_url", AppConfig.flaresolverr_url),
        products=products,
        notifiers=notifiers,
    )
