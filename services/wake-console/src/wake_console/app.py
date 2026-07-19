from __future__ import annotations

import hmac
import html
import ipaddress
import os
import secrets
import socket
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

MAX_BODY_BYTES = 1024


@dataclass(frozen=True)
class Config:
    target_name: str
    target_mac: bytes
    broadcast_address: str
    broadcast_port: int
    allowed_host: str
    allowed_origin: str
    listen_address: str = "0.0.0.0"
    listen_port: int = 8088
    packet_count: int = 3
    packet_interval_seconds: float = 0.15
    minimum_wake_interval_seconds: float = 3.0

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Config:
        values = os.environ if env is None else env
        required = (
            "WAKE_TARGET_NAME",
            "WAKE_TARGET_MAC",
            "WAKE_BROADCAST_ADDRESS",
            "WAKE_ALLOWED_HOST",
            "WAKE_ALLOWED_ORIGIN",
        )
        missing = [name for name in required if not values.get(name)]
        if missing:
            message = f"Missing required environment variables: {', '.join(missing)}"
            raise ValueError(message)

        broadcast_address = str(ipaddress.IPv4Address(values["WAKE_BROADCAST_ADDRESS"]))
        allowed_host = values["WAKE_ALLOWED_HOST"].strip().lower().rstrip(".")
        allowed_origin = values["WAKE_ALLOWED_ORIGIN"].strip().lower().rstrip("/")
        if not allowed_origin.startswith("https://"):
            raise ValueError("WAKE_ALLOWED_ORIGIN must use HTTPS")

        return cls(
            target_name=values["WAKE_TARGET_NAME"].strip(),
            target_mac=parse_mac(values["WAKE_TARGET_MAC"]),
            broadcast_address=broadcast_address,
            broadcast_port=int(values.get("WAKE_BROADCAST_PORT", "9")),
            allowed_host=allowed_host,
            allowed_origin=allowed_origin,
            listen_address=values.get("WAKE_LISTEN_ADDRESS", "0.0.0.0"),
            listen_port=int(values.get("WAKE_LISTEN_PORT", "8088")),
            packet_count=int(values.get("WAKE_PACKET_COUNT", "3")),
            packet_interval_seconds=float(values.get("WAKE_PACKET_INTERVAL_SECONDS", "0.15")),
            minimum_wake_interval_seconds=float(values.get("WAKE_MINIMUM_INTERVAL_SECONDS", "3")),
        )


def parse_mac(value: str) -> bytes:
    compact = value.replace(":", "").replace("-", "").strip()
    if len(compact) != 12:
        raise ValueError("WAKE_TARGET_MAC must contain exactly six octets")
    try:
        parsed = bytes.fromhex(compact)
    except ValueError as error:
        raise ValueError("WAKE_TARGET_MAC must be a hexadecimal MAC address") from error
    if parsed == b"\x00" * 6 or parsed == b"\xff" * 6 or parsed[0] & 1:
        raise ValueError("WAKE_TARGET_MAC must be a unicast hardware address")
    return parsed


def build_magic_packet(mac: bytes) -> bytes:
    if len(mac) != 6:
        raise ValueError("A MAC address must contain exactly six bytes")
    return b"\xff" * 6 + mac * 16


def send_magic_packets(config: Config) -> None:
    packet = build_magic_packet(config.target_mac)
    destination = (config.broadcast_address, config.broadcast_port)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp_socket:
        udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for packet_number in range(config.packet_count):
            udp_socket.sendto(packet, destination)
            if packet_number + 1 < config.packet_count:
                time.sleep(config.packet_interval_seconds)


class WakeController:
    def __init__(
        self,
        sender: Callable[[], None],
        minimum_interval_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._sender = sender
        self._minimum_interval_seconds = minimum_interval_seconds
        self._clock = clock
        self._last_wake = float("-inf")
        self._lock = threading.Lock()

    def wake(self) -> bool:
        with self._lock:
            now = self._clock()
            if now - self._last_wake < self._minimum_interval_seconds:
                return False
            self._sender()
            self._last_wake = now
            return True


def _page(config: Config, csrf_token: str, message: str | None = None) -> bytes:
    safe_target = html.escape(config.target_name)
    notice = f'<p class="notice" role="status">{html.escape(message)}</p>' if message else ""
    content = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Wake {safe_target}</title>
  <style>
    :root {{ color-scheme: dark; font-family: system-ui, sans-serif; }}
    body {{ min-height: 100vh; margin: 0; display: grid; place-items: center;
      background: #0c111b; color: #f5f7fb; }}
    main {{ width: min(88vw, 28rem); text-align: center; padding: 2.5rem;
      border: 1px solid #28364d; border-radius: 1.25rem; background: #121b2a;
      box-shadow: 0 1rem 3rem #0008; }}
    h1 {{ margin: 0 0 .5rem; font-size: 2rem; }}
    p {{ color: #b8c3d6; }}
    button {{ width: 100%; margin-top: 1.5rem; padding: 1.15rem; border: 0;
      border-radius: .8rem; background: #47d787; color: #07130c; font: inherit;
      font-weight: 750; font-size: 1.15rem; cursor: pointer; }}
    button:active {{ transform: translateY(1px); }}
    .notice {{ color: #72e5a5; font-weight: 650; }}
    small {{ display: block; margin-top: 1.25rem; color: #8290a8; }}
  </style>
</head>
<body>
  <main>
    <h1>{safe_target}</h1>
    <p>Send a Wake-on-WLAN magic packet from the home cluster.</p>
    {notice}
    <form method="post" action="/wake">
      <input type="hidden" name="csrf_token" value="{csrf_token}">
      <button type="submit">Wake PC</button>
    </form>
    <small>Only available on the home network</small>
  </main>
</body>
</html>
"""
    return content.encode()


def create_handler(config: Config, controller: WakeController) -> type[BaseHTTPRequestHandler]:
    class WakeRequestHandler(BaseHTTPRequestHandler):
        server_version = "WakeConsole"
        sys_version = ""

        def do_GET(self) -> None:
            if self.path == "/health":
                self._send_bytes(HTTPStatus.OK, b'{"status":"ok"}', "application/json")
                return
            if self.path != "/":
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            if not self._valid_request_context(require_origin=False):
                return
            csrf_token = secrets.token_urlsafe(32)
            self._send_bytes(
                HTTPStatus.OK,
                _page(config, csrf_token),
                "text/html; charset=utf-8",
                cookie=f"wake_csrf={csrf_token}; Path=/; Secure; HttpOnly; SameSite=Strict",
            )

        def do_POST(self) -> None:
            if self.path != "/wake":
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            if not self._valid_request_context(require_origin=True):
                return
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self.send_error(HTTPStatus.BAD_REQUEST)
                return
            if content_length < 1 or content_length > MAX_BODY_BYTES:
                self.send_error(HTTPStatus.BAD_REQUEST)
                return
            content_type = self.headers.get("Content-Type", "").split(";", maxsplit=1)[0]
            if content_type != "application/x-www-form-urlencoded":
                self.send_error(HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
                return
            try:
                body = self.rfile.read(content_length).decode("utf-8", errors="strict")
                form_token = parse_qs(body, strict_parsing=True).get("csrf_token", [""])[0]
            except (UnicodeDecodeError, ValueError):
                self.send_error(HTTPStatus.BAD_REQUEST)
                return
            cookie_token = self._cookie_value("wake_csrf")
            if not cookie_token or not hmac.compare_digest(form_token, cookie_token):
                self.send_error(HTTPStatus.FORBIDDEN, "Invalid request token")
                return

            try:
                sent = controller.wake()
            except OSError:
                self.send_error(HTTPStatus.SERVICE_UNAVAILABLE, "Wake packet could not be sent")
                return
            if not sent:
                self.send_error(HTTPStatus.TOO_MANY_REQUESTS, "Please wait before trying again")
                return

            csrf_token = secrets.token_urlsafe(32)
            timestamp = datetime.now(UTC).strftime("%H:%M:%S UTC")
            self._send_bytes(
                HTTPStatus.OK,
                _page(config, csrf_token, f"Wake packet sent at {timestamp}"),
                "text/html; charset=utf-8",
                cookie=f"wake_csrf={csrf_token}; Path=/; Secure; HttpOnly; SameSite=Strict",
            )

        def _valid_request_context(self, require_origin: bool) -> bool:
            host = self.headers.get("Host", "").split(":", maxsplit=1)[0].lower().rstrip(".")
            if host != config.allowed_host:
                self.send_error(HTTPStatus.BAD_REQUEST, "Invalid host")
                return False
            if self.headers.get("X-Forwarded-Proto", "").lower() != "https":
                self.send_error(HTTPStatus.BAD_REQUEST, "HTTPS is required")
                return False
            if require_origin:
                origin = self.headers.get("Origin", "").lower().rstrip("/")
                if origin != config.allowed_origin:
                    self.send_error(HTTPStatus.FORBIDDEN, "Invalid origin")
                    return False
            return True

        def _cookie_value(self, name: str) -> str | None:
            for item in self.headers.get("Cookie", "").split(";"):
                key, separator, value = item.strip().partition("=")
                if separator and key == name:
                    return value
            return None

        def _send_bytes(
            self,
            status: HTTPStatus,
            body: bytes,
            content_type: str,
            cookie: str | None = None,
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; "
                "base-uri 'none'; frame-ancestors 'none'",
            )
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Strict-Transport-Security", "max-age=31536000")
            self.send_header("X-Content-Type-Options", "nosniff")
            if cookie:
                self.send_header("Set-Cookie", cookie)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, message: str, *args: object) -> None:
            print(f"{self.address_string()} - {message % args}", flush=True)

    return WakeRequestHandler


def main() -> None:
    config = Config.from_env()
    controller = WakeController(
        sender=lambda: send_magic_packets(config),
        minimum_interval_seconds=config.minimum_wake_interval_seconds,
    )
    server = ThreadingHTTPServer(
        (config.listen_address, config.listen_port), create_handler(config, controller)
    )
    print(
        f"Wake console listening on {config.listen_address}:{config.listen_port} "
        f"for fixed target {config.target_name}",
        flush=True,
    )
    server.serve_forever()
