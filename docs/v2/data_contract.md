# V2 causal data contract

V2 decisions occur before processor authorization. The lifecycle is:

1. `authorization_request`: validate and deduplicate; read committed history strictly before `(timestamp, event_sequence)`; compute one feature row from history plus request-known fields; register a pending request. No outcome counter changes.
2. `authorization_outcome`: require a matching unblocked pending request; commit approval/decline and request attributes exactly once; emit no model row.
3. `checkout_completion`: require a processed approval for the same device/session, update success history once, and emit no model row.

Events use UTC timestamps and deterministic `event_id`, `request_id`, `event_sequence`, opaque device/session/IP/card fingerprints, request-known BIN, amount, normalized USD currency, merchant/campaign context, and lifecycle-specific fields. Outcome/result fields exist only on outcome events. Generation truth (`label`, `population`, `attack_subtype`, `scenario_tag`, generator parameters and split) is metadata kept out of `MODEL_FEATURES`.

Forbidden persisted fields are PAN, CVV, expiry, raw IP, and payment-provider tokens. Synthetic fingerprints are seeded counters over nonsensitive entities. A real adapter must use a rotating keyed HMAC or token-vault reference with access control; no secret is embedded here. Card-to-BIN mapping is stable and retries may reuse cards. Device, session, IP, card, and account/customer are distinct entities.

## Integrity rules

- Ordering is `(timestamp, event_sequence)`. A lower ordering key than committed state raises `LateEventError`; an online adapter must quarantine it.
- Exact duplicate event IDs are idempotent. Different content under the same ID raises `ConflictingDuplicateError`.
- Outcomes without pending requests, conflicting second outcomes, outcomes for blocked requests, cross-device/session links, and completions without a plausible processed approval raise `EventContractError`.
- A blocked request is scored but never processed. V2 reports `requests_scored_through_first_action`, `authorizations_processed_before_first_action`, `distinct_cards_requested_through_first_action`, and `distinct_cards_processed_before_first_action`—never V1 post-authorization names.
- The single-process adapter is deterministic, not concurrency-safe. Phase 4 must serialize or atomically commit per-device/request transitions.

The engine retains cumulative counters and configured seven-day histories. Eviction is deterministic after the longest window. Current-request amount, card, BIN, campaign, and prospective velocity enter once at precheck; the unknown current result never does.

IP state is updated by the same chronological lifecycle engine: scored-request
history supports prospective IP request counts, while committed outcomes add
device/session observations for processed-history IP counts. Raw train and
validation streams share realistic IP fingerprints, but development feature
construction replays each split with an independent engine. Thus the same IP
can occur in both raw partitions without cross-split feature state.
