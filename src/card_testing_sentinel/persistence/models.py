"""Storage-neutral persisted records."""

from dataclasses import dataclass


@dataclass(frozen=True)
class StoredRequest:
    request_id: str
    event_id: str
    device_hash: str
    session_hash: str
    ip_hash: str
    card_hash: str
    timestamp: str
    event_sequence: int
    payload_digest: str
    payload_json: str
    decision: str
    raw_score: float
    risk_score: float
    rule_score: int
    reason_codes_json: str
    state_version: int
    response_json: str
    latency_ms: float
    #: JSON-encoded allowlisted safe-evidence dict (the same six signals the
    #: fraud-operations panel is allowed to show), captured at decision
    #: time. Persisted so an idempotent replay can return the *original*
    #: authoritative evidence verbatim -- without recomputing a snapshot --
    #: instead of an empty projection. Defaults to "{}" so existing
    #: construction sites (including tests) that predate this field keep
    #: working unchanged.
    evidence_json: str = "{}"


@dataclass(frozen=True)
class StoredEvent:
    event_id: str
    request_id: str
    event_type: str
    device_hash: str
    session_hash: str
    timestamp: str
    event_sequence: int
    payload_digest: str
    payload_json: str
    state_version: int
