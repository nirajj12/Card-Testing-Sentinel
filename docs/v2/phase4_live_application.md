# Phase 4 live application

## Evidence boundary

> The live application uses the frozen Phase 2C policy that passed the one-time Phase 3 synthetic blind evaluation. It does not retrain, recalibrate, retune or rescore blind data.

At startup, the application verifies the frozen model, policy, Phase 3 pre-access
freeze, dataset lifecycle and final manifest before it becomes ready. The model,
calibrator, policy, frozen metrics and saved blind decisions are loaded once. The
blind dashboard endpoints only filter those saved decisions.

## Architecture and scoring moment

The same-origin browser uses Jinja2-rendered HTML, CSS and native JavaScript ES
modules. FastAPI validates raw lifecycle requests. `LiveScoringService` performs
the causal transition under one process-wide asynchronous lock. The frozen
`Phase2BFeatureEngine`, optimized model/calibrator adapter and Phase 2C
`StatefulPolicy` remain the decision-critical implementation.

For each authorization request, features are computed immediately before its
decision. The request has no outcome yet. The frozen model returns a risk score,
the frozen policy returns allow/review/block, and only then is request-side state
committed. A later accepted outcome or checkout can affect only future requests.
A block suppresses only its linked outcome and checkout; the device is not
permanently banned and its later requests are independently scored.

## API contracts

- `GET /`, `/health/live`, `/health/ready`, `/api/v2/system`
- `POST /api/v2/precheck`, `/api/v2/outcomes`, `/api/v2/checkouts`
- `GET /api/v2/runtime/decisions`
- `GET /api/v2/runtime/devices/{device_id}/timeline`
- `GET /api/v2/metrics/blind`, `/api/v2/replay/devices`
- `GET /api/v2/replay/devices/{device_id}/timeline`
- When demo mode is enabled: `GET /api/v2/demo/scenarios` and `POST`
  `/api/v2/demo/start`, `/api/v2/demo/step`, `/api/v2/demo/reset`

Unknown fields and client-computed features are rejected. Precheck responses
contain only the decision, risk score, rule evidence, safe versions, state
version, processing time and latency—not internal thresholds or raw features.

The following examples deliberately use fake tokens and documentation-only
addresses:

```bash
curl -sS http://127.0.0.1:8000/api/v2/precheck \
  -H 'Content-Type: application/json' \
  -d '{
    "request_id":"fake-request-0001",
    "event_id":"fake-precheck-0001",
    "device_id":"fake-device-0001",
    "session_id":"fake-session-0001",
    "card_reference":"fake-gateway-token-0001",
    "card_bin":"410000",
    "ip_reference":"opaque-network-reference-0001",
    "amount":2.00,
    "currency":"USD",
    "timestamp":"2030-01-01T00:00:00Z",
    "event_sequence":1,
    "campaign_active":false
  }'
```

```bash
curl -sS http://127.0.0.1:8000/api/v2/outcomes \
  -H 'Content-Type: application/json' \
  -d '{
    "event_id":"fake-outcome-0001",
    "request_id":"fake-request-0001",
    "device_id":"fake-device-0001",
    "session_id":"fake-session-0001",
    "timestamp":"2030-01-01T00:00:01Z",
    "event_sequence":2,
    "authorization_result":"approved",
    "decline_reason":null
  }'
```

```bash
curl -sS http://127.0.0.1:8000/api/v2/checkouts \
  -H 'Content-Type: application/json' \
  -d '{
    "event_id":"fake-checkout-0001",
    "request_id":"fake-request-0001",
    "device_id":"fake-device-0001",
    "session_id":"fake-session-0001",
    "timestamp":"2030-01-01T00:00:02Z",
    "event_sequence":3
  }'
```

## Persistence, idempotency and security

SQLite uses foreign keys, WAL, full synchronous writes, unique transition
constraints and explicit transactions. The default mutable database is
`data/v2/phase4/runtime/live_state.sqlite3`; it is not a frozen artifact. On
restart, the engine and policy state are causally rebuilt from sanitized stored
events, with decisions and state versions verified. No model rescore is needed.

Each new accepted transition increments the relevant frozen device state version.
An identical retry returns the original decision and state version, sets
`idempotent_replay`, and neither scores nor commits twice. Reusing an identifier
with different normalized content returns HTTP 409. Older causal positions are
also rejected with HTTP 409; timestamp ties use `event_sequence`.

Set `CTS_HMAC_SECRET` to a private, high-entropy value. Startup remains not-ready
without it. Device, session, gateway card-token and IP references are separated
by domain and transformed with HMAC-SHA256 before persistence. The database and
logs do not store raw card tokens or IP addresses, and the API rejects PAN, CVV
and expiry fields. The example secret is a placeholder only:

```bash
export CTS_HMAC_SECRET='replace-with-a-private-high-entropy-secret'
```

## Run and verify

Use only the canonical environment:

```bash
/Users/nirajmac/envs/card-testing-sentinel-v2b/bin/python scripts/v2/phase4/run_app.py
```

Then open `http://127.0.0.1:8000`. To test and measure coverage:

```bash
/Users/nirajmac/envs/card-testing-sentinel-v2b/bin/python -m pytest tests/v2/phase4
/Users/nirajmac/envs/card-testing-sentinel-v2b/bin/python -m pytest
```

Run the non-gating local benchmark and runtime verifier with:

```bash
/Users/nirajmac/envs/card-testing-sentinel-v2b/bin/python scripts/v2/phase4/benchmark_live_api.py
/Users/nirajmac/envs/card-testing-sentinel-v2b/bin/python scripts/v2/phase4/verify_phase4.py --runtime
```

The dashboard has Overview, Live Detection, Blind Replay and System views. Live
Detection executes isolated demo raw events through the same service stack. Blind
Replay filters immutable Phase 3 decisions and never calls the live scorer.

## Limits and production upgrade path

This is a synthetic, local, single-process demonstration—not a production
payment network. A global lock prioritizes causal correctness but does not provide
horizontal scale. Results require validation on real merchant traffic, drift
monitoring and human-review feedback. Risk score is not a guaranteed fraud
probability, early detection is limited, and the offline potentially preventable
count is an upper-bound estimate rather than observed prevention.

A production design would use a transactional distributed state store such as
Redis, device/IP partitioning, durable event streaming, distributed idempotency,
multiple API workers, audited secret management, authentication and authorization,
rate limiting, observability, retention policies and controlled state migrations.
