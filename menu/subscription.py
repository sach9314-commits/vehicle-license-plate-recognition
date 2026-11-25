import base64
from contextlib import closing
import hashlib
import hmac
import json
import logging
import os
import secrets
import sqlite3
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request as URLRequest
from urllib.request import urlopen

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

PROJECT_DIR = Path(__file__).resolve().parent.parent
DATABASE_PATH = Path(os.getenv("DRISHTI_SUBSCRIPTION_DB", PROJECT_DIR / "subscriptions.sqlite3"))
COOKIE_NAME = "drishti_subscriber"
DEMO_COOKIE_NAME = "drishti_demo_access"
DEMO_ACCESS_SECONDS = 4 * 60 * 60
SUBSCRIPTION_PRICE_PAISE = 9900
SUBSCRIPTION_CURRENCY = "INR"
SUBSCRIPTION_PERIOD = "monthly"
SUBSCRIPTION_TOTAL_CYCLES = 120
SUBSCRIPTION_WEBHOOK_EVENTS = {
    "subscription.activated",
    "subscription.charged",
    "subscription.resumed",
    "subscription.authenticated",
    "subscription.pending",
    "subscription.paused",
    "subscription.halted",
    "subscription.cancelled",
    "subscription.completed",
    "subscription.expired",
    "subscription.updated",
}
SUBSCRIPTION_STATUSES = {
    "created",
    "authenticated",
    "active",
    "pending",
    "halted",
    "cancelled",
    "completed",
    "expired",
    "paused",
}
logger = logging.getLogger(__name__)
router = APIRouter()

PAYWALL_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Tracking + Traffic subscription - DrishtiDrive</title>
  <script defer src="https://checkout.razorpay.com/v1/checkout.js"></script>
  <style>
    body{margin:0;min-height:100vh;display:grid;place-items:center;background:#101820;color:#f5f7fa;
      font:16px system-ui,sans-serif}.card{width:min(440px,calc(100% - 40px));padding:32px;border:1px solid #35424c;
      border-radius:18px;background:#1a2731;box-sizing:border-box}h1{margin-top:0}p{line-height:1.55;color:#c5d0d8}
    button{width:100%;padding:14px;border:0;border-radius:9px;background:#f5a623;color:#171717;font-size:16px;
      font-weight:700;cursor:pointer}button:disabled{opacity:.6;cursor:wait}#message{min-height:24px}
    button+button{margin-top:10px;background:#d1d5db}.demo-note{font-size:13px;text-align:center}
    a{color:#f5a623}
  </style>
</head>
<body>
  <main class="card">
    <h1>Unlock Tracking + Traffic</h1>
    <p>Tracking / OCR and Traffic are included for ₹99 per month. ANPR live detection remains free.</p>
    <button id="subscribe" type="button">Subscribe for ₹99/month</button>
    <!-- DEMO_ACCESS_OPTION -->
    <p id="message" role="status" aria-live="polite"></p>
    <a href="/">Back to DrishtiDrive</a>
  </main>
  <script>
    const button = document.getElementById('subscribe');
    const demoButton = document.getElementById('demo-access');
    const message = document.getElementById('message');
    const destination = new URLSearchParams(window.location.search).get('next') === '/traffic/'
      ? '/traffic/'
      : '/tracking/';
    const paymentPage = new URLSearchParams(window.location.search).get('payment') === '1';
    const setMessage = text => { message.textContent = text; };

    async function readStatus() {
      const response = await fetch('/api/subscription/status');
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Unable to check subscription status.');
      return data;
    }

    async function waitForActivation() {
      setMessage('Payment received. Confirming your subscription…');
      for (let attempt = 0; attempt < 30; attempt += 1) {
        const status = await readStatus();
        if (status.active) {
          window.location.assign(destination);
          return;
        }
        await new Promise(resolve => setTimeout(resolve, 2000));
      }
      setMessage('Payment is being confirmed. Refresh this page in a moment.');
    }

    button.addEventListener('click', async () => {
      button.disabled = true;
      setMessage('Opening secure checkout…');
      try {
        if (typeof window.Razorpay !== 'function') {
          throw new Error('Secure checkout could not load. Check your internet connection and try again.');
        }
        const response = await fetch('/api/subscription/create', { method: 'POST' });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || 'Could not start checkout.');
        if (data.active) {
          window.location.assign(destination);
          return;
        }
        const checkout = new Razorpay({
          key: data.key_id,
          subscription_id: data.subscription_id,
          name: 'DrishtiDrive',
          description: 'Tracking + Traffic - ₹99/month',
          theme: { color: '#f5a623' },
          handler: async payment => {
            try {
              const verification = await fetch('/api/subscription/verify', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payment)
              });
              const result = await verification.json();
              if (!verification.ok) throw new Error(result.detail || 'Payment verification failed.');
              await waitForActivation();
            } catch (error) {
              setMessage(error.message);
              button.disabled = false;
            }
          },
          modal: {
            ondismiss: () => {
              setMessage('Checkout was closed. You can try again anytime.');
              button.disabled = false;
            }
          }
        });
        checkout.on('payment.failed', event => {
          setMessage(event.error?.description || 'Payment failed. Please try again.');
          button.disabled = false;
        });
        checkout.open();
      } catch (error) {
        setMessage(error.message);
        button.disabled = false;
      }
    });

    if (demoButton) {
      demoButton.addEventListener('click', async () => {
        demoButton.disabled = true;
        setMessage('Enabling judge demo access — no payment will be taken…');
        try {
          const response = await fetch('/api/subscription/demo', { method: 'POST' });
          const data = await response.json();
          if (!response.ok) throw new Error(data.detail || 'Could not enable demo access.');
          window.location.assign(destination);
        } catch (error) {
          setMessage(error.message);
          demoButton.disabled = false;
        }
      });
    }

    readStatus().then(status => {
      if (status.active && !paymentPage) {
        window.location.assign(destination);
      } else if (status.demo) {
        setMessage('Judge demo access is active; no payment was taken. Subscribe opens real checkout.');
      } else if (status.active) {
        setMessage('Your subscription is active. No further payment is due.');
      }
    }).catch(error => setMessage(error.message));
  </script>
</body>
</html>"""


class CheckoutVerification(BaseModel):
    razorpay_payment_id: str
    razorpay_subscription_id: str
    razorpay_signature: str


def _database_connection() -> sqlite3.Connection:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS subscriptions (
            browser_ref TEXT NOT NULL,
            razorpay_subscription_id TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL,
            cancel_at_cycle_end INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(subscriptions)")
    }
    if "cancel_at_cycle_end" not in columns:
        connection.execute(
            "ALTER TABLE subscriptions ADD COLUMN cancel_at_cycle_end INTEGER NOT NULL DEFAULT 0"
        )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS subscriptions_browser_ref ON subscriptions(browser_ref)"
    )
    return connection


def _session_secret() -> bytes:
    secret = os.getenv("DRISHTI_SESSION_SECRET")
    if not secret or len(secret.encode("utf-8")) < 32:
        raise HTTPException(
            status_code=503,
            detail="Payment setup is incomplete: DRISHTI_SESSION_SECRET must be at least 32 bytes.",
        )
    return secret.encode("utf-8")


def _demo_mode_enabled() -> bool:
    return os.getenv("DRISHTI_DEMO_MODE", "").strip().lower() == "true"


def is_demo_access(request: Request) -> bool:
    if not _demo_mode_enabled():
        return False
    value = request.cookies.get(DEMO_COOKIE_NAME, "")
    try:
        payload, signature = value.rsplit(".", 1)
        expires_at_text, _ = payload.split(".", 1)
        expires_at = int(expires_at_text)
    except (ValueError, TypeError):
        return False
    if expires_at <= int(time.time()):
        return False
    expected = hmac.new(
        _session_secret(),
        f"demo:{payload}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(signature, expected)


def _browser_ref_from_cookie(request: Request) -> str | None:
    value = request.cookies.get(COOKIE_NAME, "")
    try:
        token, signature = value.rsplit(".", 1)
    except ValueError:
        return None
    expected = hmac.new(_session_secret(), token.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _browser_ref(request: Request, response: Response) -> str:
    existing_ref = _browser_ref_from_cookie(request)
    if existing_ref:
        return existing_ref
    token = secrets.token_urlsafe(32)
    signature = hmac.new(_session_secret(), token.encode("utf-8"), hashlib.sha256).hexdigest()
    response.set_cookie(
        COOKIE_NAME,
        f"{token}.{signature}",
        max_age=60 * 60 * 24 * 365,
        httponly=True,
        secure=(
            request.url.scheme == "https"
            or os.getenv("DRISHTI_COOKIE_SECURE", "").lower() == "true"
        ),
        samesite="lax",
        path="/",
    )
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _subscription_for_browser(browser_ref: str) -> sqlite3.Row | None:
    with closing(_database_connection()) as connection, connection:
        return connection.execute(
            """
            SELECT razorpay_subscription_id, status, cancel_at_cycle_end
            FROM subscriptions
            WHERE browser_ref = ?
            ORDER BY updated_at DESC, rowid DESC
            LIMIT 1
            """,
            (browser_ref,),
        ).fetchone()


def is_subscription_active(request: Request) -> bool:
    browser_ref = _browser_ref_from_cookie(request)
    if browser_ref:
        subscription = _subscription_for_browser(browser_ref)
        if subscription and subscription["status"] == "active":
            return True
    return is_demo_access(request)


async def require_tracking_subscription(request: Request) -> None:
    if not is_subscription_active(request):
        raise HTTPException(
            status_code=402,
            detail="An active ₹99/month subscription is required for Tracking / OCR and Traffic.",
        )


def _razorpay_credentials() -> tuple[str, str]:
    key_id = os.getenv("RAZORPAY_KEY_ID")
    key_secret = os.getenv("RAZORPAY_KEY_SECRET")
    if not key_id or not key_secret:
        raise HTTPException(
            status_code=503,
            detail="Payment setup is incomplete: Razorpay API credentials are not configured.",
        )
    return key_id, key_secret


def _razorpay_request(method: str, endpoint: str, payload: dict | None = None) -> dict:
    key_id, key_secret = _razorpay_credentials()
    auth = base64.b64encode(f"{key_id}:{key_secret}".encode("utf-8")).decode("ascii")
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = URLRequest(
        f"https://api.razorpay.com/v1{endpoint}",
        data=body,
        headers={
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/json",
        },
        method=method,
    )
    try:
        with urlopen(request, timeout=15) as result:
            response_data = json.loads(result.read().decode("utf-8"))
            if not isinstance(response_data, dict):
                raise HTTPException(
                    status_code=502,
                    detail="Razorpay returned an invalid response.",
                )
            return response_data
    except HTTPError as error:
        logger.error("Razorpay API returned HTTP %s for %s", error.code, endpoint)
        raise HTTPException(
            status_code=502,
            detail="Razorpay could not process the request. Check the payment configuration.",
        ) from error
    except (URLError, TimeoutError) as error:
        logger.error("Razorpay API request failed for %s: %s", endpoint, error)
        raise HTTPException(
            status_code=502,
            detail="Razorpay is temporarily unavailable. Please try again.",
        ) from error
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        logger.error("Razorpay returned an unreadable response for %s", endpoint)
        raise HTTPException(
            status_code=502,
            detail="Razorpay returned an invalid response.",
        ) from error


def _configured_plan_id() -> str:
    plan_id = os.getenv("RAZORPAY_PLAN_ID")
    if not plan_id:
        raise HTTPException(
            status_code=503,
            detail="Payment setup is incomplete: create the ₹99/month INR plan and set RAZORPAY_PLAN_ID.",
        )
    return plan_id


async def _verify_plan(plan_id: str) -> None:
    plan = await run_in_threadpool(
        _razorpay_request, "GET", f"/plans/{quote(plan_id, safe='')}"
    )
    item = plan.get("item") or {}
    if (
        plan.get("period") != SUBSCRIPTION_PERIOD
        or plan.get("interval") != 1
        or item.get("amount") != SUBSCRIPTION_PRICE_PAISE
        or item.get("currency") != SUBSCRIPTION_CURRENCY
    ):
        raise HTTPException(
            status_code=503,
            detail="The configured Razorpay plan must be ₹99 INR billed monthly.",
        )


def _store_subscription(browser_ref: str, subscription_id: str, status: str) -> None:
    with closing(_database_connection()) as connection, connection:
        connection.execute(
            """
            INSERT INTO subscriptions (browser_ref, razorpay_subscription_id, status)
            VALUES (?, ?, ?)
            ON CONFLICT(razorpay_subscription_id)
            DO UPDATE SET
                status = excluded.status,
                cancel_at_cycle_end = 0,
                updated_at = CURRENT_TIMESTAMP
            """,
            (browser_ref, subscription_id, status),
        )


def _update_subscription_status(subscription_id: str, status: str) -> None:
    with closing(_database_connection()) as connection, connection:
        connection.execute(
            """
            UPDATE subscriptions
            SET status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE razorpay_subscription_id = ?
            """,
            (status, subscription_id),
        )


def _subscription_is_registered(subscription_id: str) -> bool:
    with closing(_database_connection()) as connection, connection:
        return connection.execute(
            "SELECT 1 FROM subscriptions WHERE razorpay_subscription_id = ?",
            (subscription_id,),
        ).fetchone() is not None


def _mark_cancel_at_cycle_end(subscription_id: str) -> None:
    with closing(_database_connection()) as connection, connection:
        connection.execute(
            """
            UPDATE subscriptions
            SET cancel_at_cycle_end = 1, updated_at = CURRENT_TIMESTAMP
            WHERE razorpay_subscription_id = ?
            """,
            (subscription_id,),
        )


@router.get("/api/subscription/status")
async def subscription_status(request: Request, response: Response):
    browser_ref = _browser_ref(request, response)
    subscription = _subscription_for_browser(browser_ref)
    has_paid_subscription = bool(subscription and subscription["status"] == "active")
    demo = is_demo_access(request) and not has_paid_subscription
    if has_paid_subscription:
        status = subscription["status"]
    elif demo:
        status = "demo"
    else:
        status = subscription["status"] if subscription else "inactive"
    return {
        "active": demo or has_paid_subscription,
        "demo": demo,
        "status": status,
        "price_paise": SUBSCRIPTION_PRICE_PAISE,
        "currency": SUBSCRIPTION_CURRENCY,
        "key_id": os.getenv("RAZORPAY_KEY_ID"),
        "cancel_at_cycle_end": bool(
            subscription and subscription["cancel_at_cycle_end"]
        ),
    }


@router.post("/api/subscription/demo")
async def start_demo_access(request: Request, response: Response):
    if not _demo_mode_enabled():
        raise HTTPException(status_code=404, detail="Demo access is disabled.")

    _browser_ref(request, response)
    expires_at = int(time.time()) + DEMO_ACCESS_SECONDS
    payload = f"{expires_at}.{secrets.token_urlsafe(24)}"
    signature = hmac.new(
        _session_secret(),
        f"demo:{payload}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    response.set_cookie(
        DEMO_COOKIE_NAME,
        f"{payload}.{signature}",
        max_age=DEMO_ACCESS_SECONDS,
        httponly=True,
        secure=(
            request.url.scheme == "https"
            or os.getenv("DRISHTI_COOKIE_SECURE", "").lower() == "true"
        ),
        samesite="lax",
        path="/",
    )
    return {
        "active": True,
        "demo": True,
        "expires_in_seconds": DEMO_ACCESS_SECONDS,
    }


@router.post("/api/subscription/create")
async def create_subscription(request: Request, response: Response):
    browser_ref = _browser_ref(request, response)
    current = _subscription_for_browser(browser_ref)
    if current and current["status"] == "active":
        return {"active": True, "status": "active"}
    if current and current["status"] in {"created", "authenticated", "pending"}:
        return {
            "active": False,
            "subscription_id": current["razorpay_subscription_id"],
            "key_id": _razorpay_credentials()[0],
        }

    plan_id = _configured_plan_id()
    await _verify_plan(plan_id)
    created = await run_in_threadpool(
        _razorpay_request,
        "POST",
        "/subscriptions",
        {
            "plan_id": plan_id,
            "total_count": SUBSCRIPTION_TOTAL_CYCLES,
            "customer_notify": True,
            "notes": {"browser_ref": browser_ref},
        },
    )
    subscription_id = created.get("id")
    if not subscription_id:
        raise HTTPException(status_code=502, detail="Razorpay did not return a subscription ID.")
    _store_subscription(browser_ref, subscription_id, created.get("status", "created"))
    return {
        "active": False,
        "subscription_id": subscription_id,
        "key_id": _razorpay_credentials()[0],
    }


@router.post("/api/subscription/verify")
async def verify_checkout(
    payload: CheckoutVerification,
    request: Request,
):
    browser_ref = _browser_ref_from_cookie(request)
    if not browser_ref:
        raise HTTPException(status_code=401, detail="Refresh the page and retry checkout.")
    subscription = _subscription_for_browser(browser_ref)
    if (
        not subscription
        or subscription["razorpay_subscription_id"] != payload.razorpay_subscription_id
    ):
        raise HTTPException(status_code=400, detail="This subscription does not belong to this browser.")

    _, key_secret = _razorpay_credentials()
    signed_data = f"{payload.razorpay_payment_id}|{payload.razorpay_subscription_id}"
    expected = hmac.new(key_secret.encode("utf-8"), signed_data.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(payload.razorpay_signature, expected):
        raise HTTPException(status_code=400, detail="Razorpay payment signature is invalid.")

    remote = await run_in_threadpool(
        _razorpay_request,
        "GET",
        f"/subscriptions/{quote(payload.razorpay_subscription_id, safe='')}",
    )
    remote_status = remote.get("status")
    if remote_status == "active":
        _update_subscription_status(payload.razorpay_subscription_id, "active")
    elif remote_status in {"authenticated", "pending"}:
        _update_subscription_status(payload.razorpay_subscription_id, remote_status)
    elif remote_status in {"cancelled", "completed", "expired", "halted"}:
        _update_subscription_status(payload.razorpay_subscription_id, remote_status)
    return {"verified": True, "status": remote_status or "pending"}


@router.post("/api/subscription/webhook")
async def razorpay_webhook(request: Request):
    webhook_secret = os.getenv("RAZORPAY_WEBHOOK_SECRET")
    if not webhook_secret:
        raise HTTPException(
            status_code=503,
            detail="Payment setup is incomplete: RAZORPAY_WEBHOOK_SECRET is not configured.",
        )
    body = await request.body()
    signature = request.headers.get("X-Razorpay-Signature", "")
    expected = hmac.new(webhook_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    if not signature or not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=400, detail="Razorpay webhook signature is invalid.")
    try:
        event_data = json.loads(body)
    except json.JSONDecodeError as error:
        raise HTTPException(status_code=400, detail="Webhook body must be valid JSON.") from error
    if not isinstance(event_data, dict):
        raise HTTPException(status_code=400, detail="Webhook body must be a JSON object.")

    event = event_data.get("event")
    event_payload = event_data.get("payload")
    if not isinstance(event_payload, dict):
        return {"received": True}
    subscription_payload = event_payload.get("subscription")
    if not isinstance(subscription_payload, dict):
        return {"received": True}
    entity = subscription_payload.get("entity")
    if not isinstance(entity, dict):
        return {"received": True}
    subscription_id = entity.get("id")
    if not subscription_id or event not in SUBSCRIPTION_WEBHOOK_EVENTS:
        return {"received": True}
    if not _subscription_is_registered(subscription_id):
        return {"received": True}

    remote = await run_in_threadpool(
        _razorpay_request,
        "GET",
        f"/subscriptions/{quote(subscription_id, safe='')}",
    )
    status = remote.get("status")
    if status not in SUBSCRIPTION_STATUSES:
        raise HTTPException(
            status_code=502,
            detail="Razorpay returned an unknown subscription status.",
        )
    _update_subscription_status(subscription_id, status)
    return {"received": True}


@router.post("/api/subscription/cancel")
async def cancel_subscription(request: Request):
    browser_ref = _browser_ref_from_cookie(request)
    if not browser_ref:
        raise HTTPException(status_code=401, detail="Subscription session is missing.")
    subscription = _subscription_for_browser(browser_ref)
    if not subscription or subscription["status"] != "active":
        raise HTTPException(status_code=404, detail="No active subscription was found.")
    result = await run_in_threadpool(
        _razorpay_request,
        "POST",
        f"/subscriptions/{quote(subscription['razorpay_subscription_id'], safe='')}/cancel",
        {"cancel_at_cycle_end": True},
    )
    _mark_cancel_at_cycle_end(subscription["razorpay_subscription_id"])
    return {"status": result.get("status", "active"), "cancel_at_cycle_end": True}


def _render_paywall() -> HTMLResponse:
    demo_option = ""
    if _demo_mode_enabled():
        demo_option = """
    <button id="demo-access" type="button">Enter judge demo — no payment</button>
    <p class="demo-note">Demo access lasts 4 hours. No charge is made.</p>
        """
    return HTMLResponse(
        PAYWALL_HTML.replace("<!-- DEMO_ACCESS_OPTION -->", demo_option),
        status_code=200,
    )


async def subscription_page(request: Request):
    return _render_paywall()


async def tracking_page(request: Request):
    if is_subscription_active(request):
        from fastapi.responses import FileResponse

        return FileResponse(PROJECT_DIR / "menu" / "tracking and ocr" / "index.html")
    return _render_paywall()


router.add_api_route("/tracking", tracking_page, methods=["GET"], include_in_schema=False)
router.add_api_route("/tracking/", tracking_page, methods=["GET"], include_in_schema=False)
router.add_api_route("/tracking/index.html", tracking_page, methods=["GET"], include_in_schema=False)
router.add_api_route("/subscription", subscription_page, methods=["GET"], include_in_schema=False)
router.add_api_route("/subscription/", subscription_page, methods=["GET"], include_in_schema=False)
