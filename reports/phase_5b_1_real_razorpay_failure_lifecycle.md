# Phase 5B.1 — Real Razorpay Failure Lifecycle and Retry Boundary

## 1. Starting commit

The phase started from `f8b24ce168f1f0ead5a4f3a5b48b1edc57c33d8a` with a clean working tree.

## 2. Observed bug

One merchant-side Pay click created one Sentinel precheck and one Razorpay Test order, but Razorpay Checkout could offer additional processor retries inside the same modal. Those retries did not create new Sentinel requests. A browser `payment.failed` event remained `failed_unverified` / `awaiting_signed_webhook`, so the decline could not enter behavioral history until a correctly signed server webhook arrived.

## 3. Root cause

The Checkout configuration used Razorpay's default retry behavior. Sentinel correctly creates a precheck only inside the merchant-side `pay()` function; Razorpay-internal retries therefore reused the already-created order and decision. The browser failure event was intentionally non-authoritative, while trusted decline history was correctly restricted to the signed webhook path.

## 4. Razorpay internal retry behavior

Standard Checkout now receives `retry: { enabled: false }`. Razorpay documents this as the supported web configuration for disabling Checkout payment retry. No unsupported web `max_count` option is used.

## 5. Fix implemented

- Disabled Razorpay-internal retries.
- Preserved a browser-failure marker across the modal's post-failure `ondismiss` callback.
- Kept browser failure untrusted and refreshed durable backend activity for the current protected attempt.
- Added a clear `Try payment again with Sentinel` merchant action after failure.
- Removed the optimistic frontend activity row for merchant payments; activity now comes from durable backend ordering.
- A new Pay click still creates a new request ID, event ID, and precheck.

## 6. Browser trust boundary

The browser `payment.failed` event only displays the decline and the `awaiting_signed_webhook` state. It does not call payment verification, record an authorization outcome, fabricate a webhook, or mark the history as declined. The displayed message is:

> Payment was declined. Sentinel is waiting for the signed Razorpay server event before using this result as behavioral history.

## 7. Webhook trust boundary

`POST /api/webhooks/razorpay` continues to validate the raw request body with `RAZORPAY_WEBHOOK_SECRET` and the `X-Razorpay-Signature` header. It also requires `x-razorpay-event-id` for delivery-level idempotency. Browser trust was not substituted for this path.

## 8. `payment.failed` processing

A valid signed `payment.failed` payload correlates its Razorpay payment to the stored Razorpay order and from that order to the original Sentinel request. The backend stores payment status `failed`, records a trusted `authorization_outcome` of `declined`, and exposes history status `recorded_declined`. The UI then reports:

> Verified decline recorded. A new Pay attempt will be evaluated with this history.

Invalid signatures mutate no payment, webhook-delivery, or behavioral-history state. Supported signed events remain `payment.failed`, `payment.authorized`, `payment.captured`, and `order.paid`.

## 9. Retry and new-precheck lifecycle

The intended lifecycle is now enforced at the Checkout boundary:

1. One merchant Pay click creates one Sentinel precheck.
2. An ALLOW may create one idempotent Razorpay order and open one non-retrying Checkout.
3. The browser may report a failure, but only the signed server event makes it trusted history.
4. The next merchant Pay click creates a new Sentinel precheck and a new request/event pair.
5. The frozen model decides the new attempt naturally; no REVIEW or BLOCK outcome is forced.

## 10. Durable attempt counting

Recent Payment Activity is populated from backend `recent_activity` results ordered by stored request timestamp and event sequence. Three sequential protected requests produce three distinct activity IDs and three rows. Each signed failure remains one payment on its own Razorpay order. Razorpay-internal UI events do not create activity rows.

## 11. Automated test results

- Frontend: 69 passed — 31 legacy and 38 React tests.
- Targeted Razorpay backend: 12 passed.
- Full Python suite: 275 passed, 262 deselected; one existing physical-core detection warning.
- Frontend production build: passed, 2,105 modules transformed.
- Historical runtime verifier: passed.
- Active v3.1 runtime verifier: passed without rescoring.

Coverage includes disabled Checkout retry, non-authoritative browser failure, modal dismissal preservation, verified-decline UI refresh, new request/event identifiers, retained shopper/device/session identity, increasing event sequence, durable three-attempt activity, signed failure recording, invalid signature rejection, delivery idempotency, causal future-only feature history, successful payment verification, REVIEW/BLOCK order suppression, and monotonic out-of-order webhook handling.

## 12. Manual E2E status

**EXTERNAL RAZORPAY WEBHOOK DELIVERY NOT YET VERIFIED**

Deterministic signed webhook fixtures are verified. Actual Razorpay Test Mode delivery requires the user's Dashboard configuration and a public HTTPS tunnel to the local backend.

Configure this public endpoint in the Razorpay Test Mode Dashboard:

`https://<PUBLIC-TUNNEL>/api/webhooks/razorpay`

Use the existing `RAZORPAY_WEBHOOK_SECRET` value and subscribe to:

- `payment.failed`
- `payment.authorized`
- `payment.captured`
- `order.paid`

Manual verification checklist:

1. Start the backend on port 8000 and the frontend.
2. Start a public HTTPS tunnel to backend port 8000.
3. Configure the endpoint above in the Razorpay Test Mode Dashboard.
4. Configure the Dashboard webhook secret to match `RAZORPAY_WEBHOOK_SECRET`.
5. Subscribe to the four required events.
6. Use the same Test Mode shopper and click Pay.
7. Produce a Test Mode decline and confirm Checkout offers no internal retry.
8. Return to the merchant UI and confirm the backend receives signed `payment.failed`.
9. Confirm payment status `failed`, webhook verified `true`, and history status `recorded_declined`.
10. Click Pay again and confirm a second Sentinel request appears with the retained shopper identity and next event sequence.
11. Repeat once if useful and confirm the activity list contains separate protected attempts.

Capture only non-secret request IDs, Razorpay order IDs, payment status, webhook verification status, history status, attempt count, decisions, and safe reason/evidence summaries.

## 13. Limitations

External delivery, tunnel reachability, Dashboard subscription, and a real Test Mode decline have not been observed in this environment. The UI refresh depends on the backend receiving the signed event. Browser failure remains deliberately insufficient for trusted behavioral history.

## 14. Frozen model and evaluation confirmation

Model v3.1, the 44-feature order and formulas, Policy v2, thresholds, calibration, PBRSS evaluation, economic artifacts, and final figures were not changed. No retraining, recalibration, rescoring, threshold tuning, commit, or push was performed. `README.md` remains unchanged.
