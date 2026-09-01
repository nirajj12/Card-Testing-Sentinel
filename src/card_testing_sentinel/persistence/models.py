"""Storage-neutral persisted records."""

from dataclasses import dataclass


@dataclass(frozen=True)
class StoredRequest:
    request_id: str
    event_id: str
    merchant_hash: str
    customer_hash: str | None
    device_hash: str
    session_hash: str
    ip_hash: str
    timestamp: str
    event_sequence: int
    payload_digest: str
    payload_json: str
    decision: str
    #: null in rules_only mode -- no trained model produced a score.
    risk_score: float | None
    rule_score: int
    reason_codes_json: str
    state_version: int
    response_json: str
    latency_ms: float
    #: JSON-encoded allowlisted safe-evidence dict captured at decision time,
    #: so an idempotent replay can return the original evidence verbatim.
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


@dataclass(frozen=True)
class StoredGatewayOrder:
    sentinel_request_id: str
    razorpay_order_id: str
    amount_minor: int
    currency: str
    receipt: str
    status: str
    checkout_opened: bool = False


@dataclass(frozen=True)
class StoredGatewayPayment:
    razorpay_payment_id: str
    razorpay_order_id: str
    sentinel_request_id: str
    status: str
    signature_verified: bool = False
    webhook_verified: bool = False
    history_status: str = "pending"


@dataclass(frozen=True)
class StoredWebhookDelivery:
    event_id: str
    payload_digest: str
    event_type: str
