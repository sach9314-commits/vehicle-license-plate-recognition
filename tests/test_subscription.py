import asyncio
import hashlib
import hmac
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException, Request, Response

from menu import subscription


class SubscriptionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "subscriptions.sqlite3"
        self.database_patch = patch.object(subscription, "DATABASE_PATH", self.database_path)
        self.database_patch.start()
        self.environment_patch = patch.dict(
            os.environ,
            {
                "DRISHTI_SESSION_SECRET": "test-session-secret-" * 3,
                "DRISHTI_DEMO_MODE": "false",
                "RAZORPAY_WEBHOOK_SECRET": "test-webhook-secret",
            },
        )
        self.environment_patch.start()

        response = Response()
        status = asyncio.run(subscription.subscription_status(self.make_request(), response))
        self.assertFalse(status["active"])
        self.cookie = response.headers["set-cookie"].split(";", 1)[0].split("=", 1)[1]
        self.browser_request = self.make_request(cookie=self.cookie)
        self.browser_ref = subscription._browser_ref_from_cookie(self.browser_request)
        self.assertIsNotNone(self.browser_ref)

    def tearDown(self):
        self.environment_patch.stop()
        self.database_patch.stop()
        self.temp_dir.cleanup()

    def make_request(self, cookie=None, body=b"", headers=None):
        request_headers = list(headers or [])
        if cookie:
            request_headers.append(
                (b"cookie", f"{subscription.COOKIE_NAME}={cookie}".encode())
            )
        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/api/subscription/webhook",
            "raw_path": b"/api/subscription/webhook",
            "query_string": b"",
            "headers": request_headers,
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
        }

        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}

        return Request(scope, receive)

    def signed_webhook(self, event, subscription_id="sub_test"):
        body = json.dumps(
            {
                "event": event,
                "payload": {
                    "subscription": {"entity": {"id": subscription_id}}
                },
            }
        ).encode()
        signature = hmac.new(
            b"test-webhook-secret", body, hashlib.sha256
        ).hexdigest()
        return self.make_request(
            body=body,
            headers=[(b"x-razorpay-signature", signature.encode())],
        )

    def test_signed_webhooks_activate_and_cancel_tracking_access(self):
        subscription._store_subscription(self.browser_ref, "sub_test", "created")
        stale_event = self.signed_webhook("subscription.authenticated")
        cancellation = self.signed_webhook("subscription.cancelled")
        with patch.object(
            subscription,
            "_razorpay_request",
            side_effect=[{"status": "active"}, {"status": "cancelled"}],
        ):
            asyncio.run(subscription.razorpay_webhook(stale_event))
            self.assertTrue(subscription.is_subscription_active(self.browser_request))
            asyncio.run(subscription.require_tracking_subscription(self.browser_request))
            asyncio.run(subscription.razorpay_webhook(cancellation))
        self.assertFalse(subscription.is_subscription_active(self.browser_request))
        with self.assertRaises(HTTPException) as error:
            asyncio.run(subscription.require_tracking_subscription(self.browser_request))
        self.assertEqual(error.exception.status_code, 402)

    def test_invalid_webhook_signature_is_rejected(self):
        body = json.dumps(
            {
                "event": "subscription.activated",
                "payload": {
                    "subscription": {"entity": {"id": "sub_test"}}
                },
            }
        ).encode()
        request = self.make_request(
            body=body,
            headers=[(b"x-razorpay-signature", b"invalid")],
        )
        with self.assertRaises(HTTPException) as error:
            asyncio.run(subscription.razorpay_webhook(request))
        self.assertEqual(error.exception.status_code, 400)

    def test_demo_access_requires_opt_in_and_expires_as_a_demo_cookie(self):
        response = Response()
        with self.assertRaises(HTTPException) as disabled_error:
            asyncio.run(subscription.start_demo_access(self.make_request(), response))
        self.assertEqual(disabled_error.exception.status_code, 404)
        default_page = asyncio.run(subscription.tracking_page(self.make_request()))
        self.assertNotIn(b"Enter judge demo", default_page.body)

        with patch.dict(os.environ, {"DRISHTI_DEMO_MODE": "true"}):
            page = asyncio.run(subscription.tracking_page(self.make_request()))
            self.assertIn(b"Enter judge demo", page.body)
            self.assertIn(b"no payment", page.body)

            response = Response()
            result = asyncio.run(
                subscription.start_demo_access(self.make_request(), response)
            )
            self.assertTrue(result["demo"])
            self.assertEqual(
                result["expires_in_seconds"],
                subscription.DEMO_ACCESS_SECONDS,
            )
            subscriber_cookie = next(
                header.decode().split(";", 1)[0].split("=", 1)[1]
                for name, header in response.raw_headers
                if name.lower() == b"set-cookie"
                and header.startswith(
                    f"{subscription.COOKIE_NAME}=".encode()
                )
            )
            browser_ref = subscription._browser_ref_from_cookie(
                self.make_request(cookie=subscriber_cookie)
            )
            self.assertIsNone(subscription._subscription_for_browser(browser_ref))
            demo_cookie = next(
                header.decode().split(";", 1)[0].split("=", 1)[1]
                for name, header in response.raw_headers
                if name.lower() == b"set-cookie"
                and header.startswith(
                    f"{subscription.DEMO_COOKIE_NAME}=".encode()
                )
            )
            request = self.make_request(
                headers=[
                    (
                        b"cookie",
                        f"{subscription.DEMO_COOKIE_NAME}={demo_cookie}".encode(),
                    )
                ]
            )
            self.assertTrue(subscription.is_demo_access(request))
            self.assertTrue(subscription.is_subscription_active(request))
            asyncio.run(
                subscription.require_tracking_subscription(request)
            )
            payment_page = asyncio.run(subscription.subscription_page(request))
            self.assertIn(b"paymentPage", payment_page.body)
            self.assertIn(b"Subscribe for", payment_page.body)
            with patch.dict(os.environ, {"RAZORPAY_PLAN_ID": ""}):
                with self.assertRaises(HTTPException) as checkout_error:
                    asyncio.run(
                        subscription.create_subscription(request, Response())
                    )
            self.assertEqual(checkout_error.exception.status_code, 503)

            expired_payload = f"{int(time.time()) - 1}.expired-demo-token"
            expired_signature = hmac.new(
                subscription._session_secret(),
                f"demo:{expired_payload}".encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
            expired_request = self.make_request(
                headers=[
                    (
                        b"cookie",
                        f"{subscription.DEMO_COOKIE_NAME}={expired_payload}.{expired_signature}".encode(),
                    )
                ]
            )
            self.assertFalse(subscription.is_demo_access(expired_request))

            tampered_request = self.make_request(
                headers=[
                    (
                        b"cookie",
                        f"{subscription.DEMO_COOKIE_NAME}={demo_cookie}tampered".encode(),
                    )
                ]
            )
            self.assertFalse(subscription.is_demo_access(tampered_request))

        self.assertFalse(subscription.is_demo_access(request))


if __name__ == "__main__":
    unittest.main()
