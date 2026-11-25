import asyncio
import unittest
from unittest.mock import patch

from fastapi import Request
from fastapi.responses import PlainTextResponse

from menu.app import require_subscription_for_traffic


class TrafficSubscriptionTests(unittest.TestCase):
    def make_request(self, path="/traffic/", accept="text/html"):
        return Request(
            {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": "GET",
                "scheme": "http",
                "path": path,
                "raw_path": path.encode(),
                "query_string": b"",
                "headers": [(b"accept", accept.encode())],
                "server": ("testserver", 80),
                "client": ("testclient", 50000),
            }
        )

    def test_traffic_page_redirects_to_shared_subscription(self):
        async def call_next(_request):
            self.fail("Unauthenticated Traffic request should be intercepted.")

        with patch("menu.app.is_subscription_active", return_value=False):
            response = asyncio.run(
                require_subscription_for_traffic(
                    self.make_request(), call_next
                )
            )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(
            response.headers["location"],
            "/tracking/?next=%2Ftraffic%2F",
        )

    def test_active_subscription_reaches_traffic(self):
        async def call_next(_request):
            return PlainTextResponse("Traffic dashboard")

        with patch("menu.app.is_subscription_active", return_value=True):
            response = asyncio.run(
                require_subscription_for_traffic(
                    self.make_request(), call_next
                )
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.body, b"Traffic dashboard")

    def test_traffic_api_returns_json_payment_gate(self):
        async def call_next(_request):
            self.fail("Unauthenticated Traffic API request should be intercepted.")

        with patch("menu.app.is_subscription_active", return_value=False):
            response = asyncio.run(
                require_subscription_for_traffic(
                    self.make_request("/traffic/api/traffic-data", "*/*"),
                    call_next,
                )
            )

        self.assertEqual(response.status_code, 402)
        self.assertIn(b"/tracking/?next=%2Ftraffic%2F", response.body)


if __name__ == "__main__":
    unittest.main()
