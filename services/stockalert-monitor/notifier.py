"""Notification channels.

Each channel implements ``send(alert)``. The dispatcher fans an alert out to
all enabled channels; a failure in one channel never blocks the others.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from config import NotifierConfig

log = logging.getLogger(__name__)


@dataclass
class Alert:
    retailer: str
    name: str
    url: str
    price: str | None

    def title(self) -> str:
        return f"{self.retailer} Restock!"

    def body(self) -> str:
        price = f"\n{self.price}" if self.price else ""
        return f"{self.name}{price}\n\nBuy:\n{self.url}"


class NtfyChannel:
    def __init__(self, cfg, client: httpx.Client):
        self.cfg = cfg
        self.client = client

    def send(self, alert: Alert) -> None:
        headers = {
            "Title": alert.title(),
            "Priority": str(self.cfg.priority),
            "Tags": ",".join(self.cfg.tags),
            "Click": alert.url,
        }
        if self.cfg.token:
            headers["Authorization"] = f"Bearer {self.cfg.token}"
        resp = self.client.post(
            f"{self.cfg.server.rstrip('/')}/{self.cfg.topic}",
            data=alert.body().encode("utf-8"),
            headers=headers,
            timeout=15,
        )
        resp.raise_for_status()
        log.info("ntfy notification sent (topic=%s)", self.cfg.topic)


class TelegramChannel:
    def __init__(self, cfg, client: httpx.Client):
        self.cfg = cfg
        self.client = client

    def send(self, alert: Alert) -> None:
        text = f"*{alert.title()}*\n\n{alert.body()}"
        resp = self.client.post(
            f"https://api.telegram.org/bot{self.cfg.bot_token}/sendMessage",
            json={
                "chat_id": self.cfg.chat_id,
                "text": text,
                "parse_mode": "Markdown",
                "disable_web_page_preview": False,
            },
            timeout=15,
        )
        resp.raise_for_status()
        log.info("telegram notification sent (chat=%s)", self.cfg.chat_id)


class Notifier:
    """Fan-out dispatcher over all enabled channels."""

    def __init__(self, cfg: NotifierConfig, client: httpx.Client):
        self.channels = []
        if cfg.ntfy.enabled and cfg.ntfy.topic:
            self.channels.append(NtfyChannel(cfg.ntfy, client))
        if cfg.telegram.enabled and cfg.telegram.bot_token and cfg.telegram.chat_id:
            self.channels.append(TelegramChannel(cfg.telegram, client))
        if not self.channels:
            log.warning("no notification channels enabled — alerts will only be logged")

    def send(self, alert: Alert) -> None:
        log.info("ALERT %s | %s | %s", alert.retailer, alert.name, alert.price)
        for channel in self.channels:
            try:
                channel.send(alert)
            except Exception as exc:
                log.error("%s failed: %s", type(channel).__name__, exc)
