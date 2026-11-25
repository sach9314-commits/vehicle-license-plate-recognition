# Razorpay monthly subscription setup

Tracking / OCR and Traffic share one ₹99 INR monthly subscription. ANPR live
detection remains available without a subscription. Traffic pages, feeds, and
APIs require an active subscription; an unauthenticated visit redirects to the
subscription page and returns to Traffic after activation.

## Razorpay configuration

1. In the Razorpay Dashboard, create a **monthly INR plan for ₹99** and copy its
   plan ID. Start with test mode credentials.
2. Set these environment variables for the process running `menu/app.py`:

   ```text
   RAZORPAY_KEY_ID=rzp_test_...
   RAZORPAY_KEY_SECRET=...
   RAZORPAY_PLAN_ID=plan_...
   RAZORPAY_WEBHOOK_SECRET=...
   DRISHTI_SESSION_SECRET=<random-secret-at-least-32-bytes>
   DRISHTI_COOKIE_SECURE=true
   ```

   The application checks that the configured plan is exactly ₹99 INR monthly
   before creating a subscription. It creates subscriptions for 120 monthly
   billing cycles (10 years); customers can cancel renewal at the end of a
   billing cycle. Generate a unique session secret and do not commit it to
   source control.
3. Configure a Razorpay webhook to call
   `https://<your-domain>/api/subscription/webhook`. Subscribe to the
   `subscription.activated`, `subscription.charged`, `subscription.resumed`,
   `subscription.authenticated`, `subscription.pending`, `subscription.paused`,
   `subscription.halted`, `subscription.cancelled`, `subscription.completed`,
   `subscription.expired`, and `subscription.updated` events. Use the same
   webhook secret in `RAZORPAY_WEBHOOK_SECRET`.
4. Run the integrated application with `python main.py` or
   `python menu/app.py`. Test checkout and webhook delivery in Razorpay test
   mode before switching to live credentials. Serve production traffic over
   HTTPS. Set `DRISHTI_COOKIE_SECURE=true` when TLS terminates at a reverse
   proxy; set it to `false` only for local HTTP.

For Docker Compose, provide the variables in the shell or an uncommitted
`.env` file and run `docker compose up --build`. Compose persists subscription
records in a named volume.

Subscription records are stored in `subscriptions.sqlite3` beside the project
by default. Set `DRISHTI_SUBSCRIPTION_DB` to a persistent writable path when
deploying in a container or on a platform with an ephemeral filesystem.

There is no user-login system in the project yet, so a subscription is bound to
the browser that completed checkout. Clearing that browser's cookies or moving
to another device will not restore access; add verified user accounts before
offering cross-device subscription recovery.

## Judge demo mode (no payment)

For a presentation without Razorpay credentials, set these variables for the
app process:

```text
DRISHTI_DEMO_MODE=true
DRISHTI_SESSION_SECRET=<random-secret-at-least-32-bytes>
```

The subscription page then shows a clearly labelled **Enter judge demo — no
payment** option. It grants signed, browser-only access to Tracking / OCR and
Traffic for four hours; it does not create a Razorpay payment or subscription.
The **Payment** link in either dashboard opens the real checkout page even
during demo access. The demo option is off by default. Keep
`DRISHTI_DEMO_MODE=false` in production.
