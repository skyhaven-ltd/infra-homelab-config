from __future__ import annotations

import http.client
import re
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from wake_console.app import (
    Config,
    WakeController,
    build_magic_packet,
    create_handler,
    parse_mac,
    send_magic_packets,
)


def test_config() -> Config:
    return Config(
        target_name="WNWSLAB01",
        target_mac=parse_mac("F4-3B-D8-7E-B6-0C"),
        broadcast_address="192.168.1.255",
        broadcast_port=9,
        allowed_host="wake.lab.skyhaven.ltd",
        allowed_origin="https://wake.lab.skyhaven.ltd",
    )


class MagicPacketTests(unittest.TestCase):
    def test_magic_packet_has_synchronisation_stream_and_sixteen_mac_copies(self) -> None:
        mac = bytes.fromhex("f43bd87eb60c")
        packet = build_magic_packet(mac)

        self.assertEqual(len(packet), 102)
        self.assertEqual(packet[:6], b"\xff" * 6)
        self.assertEqual(packet[6:], mac * 16)

    def test_parse_mac_accepts_common_separators(self) -> None:
        expected = bytes.fromhex("f43bd87eb60c")

        self.assertEqual(parse_mac("F4-3B-D8-7E-B6-0C"), expected)
        self.assertEqual(parse_mac("f4:3b:d8:7e:b6:0c"), expected)

    def test_parse_mac_rejects_multicast_and_invalid_values(self) -> None:
        for value in ("01:00:5e:00:00:01", "not-a-mac", "00:00:00:00:00:00"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_mac(value)

    @patch("wake_console.app.time.sleep")
    @patch("wake_console.app.socket.socket")
    def test_sender_broadcasts_three_packets_to_configured_destination(
        self, socket_factory: MagicMock, sleep: MagicMock
    ) -> None:
        udp_socket = socket_factory.return_value.__enter__.return_value

        send_magic_packets(test_config())

        expected_packet = build_magic_packet(bytes.fromhex("f43bd87eb60c"))
        self.assertEqual(
            udp_socket.sendto.call_args_list,
            [
                unittest.mock.call(expected_packet, ("192.168.1.255", 9)),
                unittest.mock.call(expected_packet, ("192.168.1.255", 9)),
                unittest.mock.call(expected_packet, ("192.168.1.255", 9)),
            ],
        )
        self.assertEqual(sleep.call_count, 2)


class WakeControllerTests(unittest.TestCase):
    def test_controller_rate_limits_repeated_wakes(self) -> None:
        calls: list[bool] = []
        now = [10.0]
        controller = WakeController(lambda: calls.append(True), 3.0, lambda: now[0])

        self.assertTrue(controller.wake())
        self.assertFalse(controller.wake())
        now[0] = 13.0
        self.assertTrue(controller.wake())
        self.assertEqual(len(calls), 2)


class WebTests(unittest.TestCase):
    def setUp(self) -> None:
        self.wakes = 0

        def record_wake() -> None:
            self.wakes += 1

        controller = WakeController(record_wake, 0)
        self.server = ThreadingHTTPServerForTests(create_handler(test_config(), controller))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, method: str, path: str, body: str | None = None, **headers: str):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=2)
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        response_body = response.read()
        connection.close()
        return response, response_body

    def test_health_is_available_to_kubernetes_probes(self) -> None:
        response, body = self.request("GET", "/health")

        self.assertEqual(response.status, 200)
        self.assertEqual(body, b'{"status":"ok"}')

    def test_page_preserves_origin_for_same_origin_form_posts(self) -> None:
        response, _ = self.request(
            "GET",
            "/",
            Host="wake.lab.skyhaven.ltd",
            **{"X-Forwarded-Proto": "https"},
        )

        self.assertEqual(response.status, 200)
        self.assertEqual(response.getheader("Referrer-Policy"), "same-origin")

    def test_same_origin_form_can_wake_fixed_target(self) -> None:
        headers = {
            "Host": "wake.lab.skyhaven.ltd",
            "X-Forwarded-Proto": "https",
        }
        response, page = self.request("GET", "/", **headers)
        cookie = response.getheader("Set-Cookie").split(";", maxsplit=1)[0]
        csrf_value = re.search(rb'name="csrf_token" value="([^"]+)"', page).group(1).decode()

        response, page = self.request(
            "POST",
            "/wake",
            body=f"csrf_token={csrf_value}",
            Cookie=cookie,
            Origin="https://wake.lab.skyhaven.ltd",
            **{"Content-Type": "application/x-www-form-urlencoded"},
            **headers,
        )

        self.assertEqual(response.status, 200)
        self.assertIn(b"Wake packet sent", page)
        self.assertEqual(self.wakes, 1)

    def test_cross_origin_post_is_rejected(self) -> None:
        response, _ = self.request(
            "POST",
            "/wake",
            body="csrf_token=anything",
            Host="wake.lab.skyhaven.ltd",
            Origin="https://attacker.example",
            Cookie="wake_csrf=anything",
            **{"Content-Type": "application/x-www-form-urlencoded"},
            **{"X-Forwarded-Proto": "https"},
        )

        self.assertEqual(response.status, 403)
        self.assertEqual(self.wakes, 0)


class ThreadingHTTPServerForTests(ThreadingHTTPServer):
    def __init__(self, handler: type[BaseHTTPRequestHandler]) -> None:
        super().__init__(("127.0.0.1", 0), handler)


if __name__ == "__main__":
    unittest.main()
