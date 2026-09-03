# API

## Precheck

`POST /api/precheck` accepts merchant-visible facts available before payment
authorization. Client-computed features, labels, scenario metadata, PAN, CVV,
expiry, card metadata and payment outcomes are rejected by a strict schema.

```json
{
  "request_id": "request-0001",
  "event_id": "precheck-0001",
  "merchant_id": "merchant-0001",
  "customer_id": "customer-0001",
  "device_id": "device-0001",
  "session_id": "session-0001",
  "ip_reference": "198.51.100.10",
  "amount": 2499.0,
  "currency": "INR",
  "timestamp": "2030-01-01T00:00:00Z",
  "event_sequence": 1,
  "campaign_active": false
}
```

The response contains the persisted `request_id` and `event_id`, decision, risk
score, rule score, safe reason codes, decision/model status, device state
version, idempotency status, processing time, latency and attempt-scoped block
metadata. It does not return internal features, thresholds, raw identifiers or
gateway secrets.

Exact precheck retries return the original persisted response with
`idempotent_replay=true`. Reusing a request or event identifier with changed
normalized content returns HTTP 409.

## Trusted payment lifecycle

The normal live API does **not** expose direct outcome or checkout-completion
write routes. Authoritative payment history enters through the Razorpay
boundary:

- `POST /api/razorpay/orders` creates a Test Mode order only for a persisted
  `ALLOW` decision;
- `POST /api/razorpay/payments/verify` verifies a Standard Checkout signature
  but does not claim an authoritative captured/failed outcome;
- `POST /api/webhooks/razorpay` verifies the HMAC-SHA256 signature over the raw
  request body, correlates the stored order/request and then records sanitized
  gateway history.

`REVIEW` and `BLOCK` suppress Razorpay order creation. Browser failure callbacks
are not authoritative payment outcomes.

## Demo simulation

`/api/demo/*` endpoints are available only when `demo_mode=true`. The server
generates their lifecycle transitions using a dedicated demo merchant and
namespaced synthetic device/session/IP identifiers. They are simulation data,
not Razorpay-verified history, and cannot be used to submit arbitrary outcomes
for live checkout identifiers.

## Read-only evidence and runtime views

- `/api/runtime/decisions` and `/api/runtime/devices/{device_id}/timeline`
  show sanitized live state.
- `/api/metrics/blind`, `/api/replay/devices` and replay timelines return saved
  synthetic evaluation evidence with `rescored: false`.
- `/api/demo/` controls the explicitly labeled, namespaced synthetic walkthrough.
