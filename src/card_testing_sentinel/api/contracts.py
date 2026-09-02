"""Strict API schemas.

The precheck request carries only raw facts a merchant owns before Razorpay
Checkout opens. It never accepts card data, payment method, a risk score, or
any client-computed feature -- Sentinel derives everything from trusted
server-side history.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from card_testing_sentinel.domain.events import (
    CardNetwork,
    CardType,
    FailureReason,
    PaymentMethod,
)

Identifier = Annotated[
    str, Field(strict=True, min_length=1, max_length=200, pattern=r"^[^\s]+$")
]
EventSequence = Annotated[int, Field(strict=True, ge=0)]
Amount = Annotated[float, Field(gt=0, le=1_000_000)]


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PrecheckRequest(StrictRequest):
    request_id: Identifier
    event_id: Identifier
    merchant_id: Identifier
    customer_id: Identifier | None = None
    device_id: Identifier
    session_id: Identifier
    ip_reference: Identifier
    amount: Amount
    currency: Literal["USD", "INR"]
    campaign_active: Annotated[bool, Field(strict=True)]
    timestamp: datetime
    event_sequence: EventSequence

    @field_validator("amount", mode="before")
    @classmethod
    def reject_boolean_amount(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("amount must be numeric, not boolean")
        return value

    @field_validator("timestamp")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must include an explicit timezone")
        return value

    @field_validator("amount")
    @classmethod
    def require_finite_amount(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("amount must be finite")
        return value


class OutcomeRequest(StrictRequest):
    event_id: Identifier
    request_id: Identifier
    device_id: Identifier
    session_id: Identifier
    timestamp: datetime
    event_sequence: EventSequence
    authorization_result: Literal["approved", "declined"]
    failure_reason: FailureReason | None = None
    # Card / method metadata from a VERIFIED Razorpay outcome. Optional,
    # historical only -- it influences future prechecks, never this one.
    payment_method: PaymentMethod | None = None
    card_last4: Annotated[str, Field(pattern=r"^\d{4}$")] | None = None
    card_network: CardNetwork | None = None
    card_type: CardType | None = None
    card_issuer: Annotated[str, Field(min_length=1, max_length=64)] | None = None
    international: bool | None = None

    @field_validator("timestamp")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must include an explicit timezone")
        return value


class CheckoutRequest(StrictRequest):
    event_id: Identifier
    request_id: Identifier
    device_id: Identifier
    session_id: Identifier
    timestamp: datetime
    event_sequence: EventSequence

    @field_validator("timestamp")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must include an explicit timezone")
        return value


class PrecheckResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    request_id: str
    event_id: str
    decision: Literal["allow", "review", "block"]
    #: null only in the degraded failover, when no model could be loaded.
    risk_score: float | None
    rule_score: int
    reason_codes: list[str]
    decision_basis: Literal["model_and_rules", "degraded_rules_only"]
    model_status: Literal["ready", "degraded_rules_only"]
    device_state_version: int
    idempotent_replay: bool
    processed_at: datetime
    latency_ms: float
    #: Policy TTL metadata retained for compatibility. The runtime does not
    #: persist or enforce a device ban until this timestamp.
    block_expires_at: datetime | None = None
    #: A block applies to this request only. Every later request is rescored
    #: from the behavioral history current at that later request.
    block_scope: Literal["current_attempt_only"] | None = None


class TransitionResponse(BaseModel):
    event_id: str
    request_id: str
    accepted: bool
    idempotent_replay: bool
    device_state_version: int
    processed_at: datetime


class DemoStartRequest(StrictRequest):
    scenario: Literal[
        "normal_customer",
        "normal_bad_luck",
        "flash_standard",
        "flash_hard_retry",
        "burst_attacker",
        "evasive_attacker",
        "patient_attacker",
    ]


class DemoStepRequest(StrictRequest):
    demo_id: Identifier


class TrafficStartRequest(StrictRequest):
    seed: int | None = Field(default=None, ge=0, lt=2**31)


class TrafficStepRequest(StrictRequest):
    traffic_run_id: Identifier


class TrafficTruthRequest(StrictRequest):
    traffic_run_id: Identifier


class RazorpayOrderRequest(StrictRequest):
    sentinel_request_id: Identifier
    device_id: Identifier
    session_id: Identifier


class RazorpayPaymentVerificationRequest(StrictRequest):
    sentinel_request_id: Identifier
    device_id: Identifier
    session_id: Identifier
    razorpay_order_id: Identifier
    razorpay_payment_id: Identifier
    razorpay_signature: Annotated[
        str, Field(min_length=64, max_length=64, pattern=r"^[a-fA-F0-9]{64}$")
    ]
