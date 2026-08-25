# V2 live-serving contract (Phase 4 design only)

Future endpoints:

- `POST /api/v2/authorizations/precheck`: raw request-known event in; frozen probability, allow/review/block_current_attempt, defensive reason codes, monotonic state version, model/policy versions, and server latency out.
- `POST /api/v2/authorizations/outcomes`: later processor result for an allowed/reviewed pending request; idempotently commits it.
- `POST /api/v2/checkouts/completions`: later completion; updates trust/history and emits no score.

The precheck action applies to the **current authorization request**. An
`allow` or `review` request may later receive one processor outcome; a
`block_current_attempt` request is never submitted and must receive no outcome.

Readiness separately verifies model, policy, feature contract, and state adapter. Liveness never implies readiness. Clients cannot choose thresholds, models, policy modes, or feature values. Strict Pydantic contracts reject missing/extra fields, Boolean-as-number, nonfinite values, and impossible transitions. Exact retries by both `event_id` and `request_id` are idempotent; conflicting duplicates return a stable conflict; late events are quarantined/rejected. Per-device/request mutation must be serialized or atomic.

State version increases after each accepted state transition and is returned
by precheck for debugging; idempotent retries return the original version.
Concurrent events for the same device/request must be serialized or committed
atomically. State/model unavailability and timeouts follow an explicitly
configured merchant fallback (for example route to merchant review); the
implementation must not silently allow or block all traffic. Model and engine
load once. Logs/responses exclude raw credentials, raw IP, full feature vectors,
labels, and sensitive payloads. Reason codes express observable risk without
publishing thresholds. Phase 4 predeclares and measures p50/p95/p99 latency
independently of offline throughput.

Offline replay and live serving call the same `precheck`, `record_outcome`, and `record_completion` methods. The local buildathon may use one in-memory process. Real deployment additionally needs durable shared state, authentication, merchant isolation, rate limits, secrets, encryption, audit logs, monitoring, and safe rollout; these are not Phase 1 deliverables.
