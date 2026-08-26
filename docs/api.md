# API

## Precheck

`POST /api/precheck` accepts a raw authorization request. Client-computed
features, labels, scenario metadata, PAN, CVV and expiry are rejected.

```json
{
  "request_id": "request-0001",
  "event_id": "precheck-0001",
  "device_id": "device-0001",
  "session_id": "session-0001",
  "card_reference": "gateway-token-0001",
  "card_bin": "410000",
  "ip_reference": "198.51.100.10",
  "amount": 2.0,
  "currency": "USD",
  "timestamp": "2030-01-01T00:00:00Z",
  "event_sequence": 1,
  "campaign_active": false
}
```

The response contains decision, risk score, rule score, safe reason codes,
artifact versions, state version and latency. It does not return internal
features or thresholds.

## Outcome and checkout

`POST /api/outcomes` records a later `approved` or `declined` result.
`POST /api/checkouts` records completion for a previously approved request.
Cross-device/session transitions, impossible state changes and late events
return HTTP 409.

Exact retries return the original state version and set `idempotent_replay`.
Reusing an event or request identifier with changed normalized content returns
HTTP 409. A blocked request cannot receive an outcome or checkout.

## Read-only evidence and runtime views

- `/api/runtime/decisions` and `/api/runtime/devices/{device_id}/timeline`
  show sanitized live state.
- `/api/metrics/blind`, `/api/replay/devices` and replay timelines return saved
  synthetic evaluation evidence with `rescored: false`.
- `/api/demo/` controls an isolated synthetic walkthrough using the real live
  scoring service.
