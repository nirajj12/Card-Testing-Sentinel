"""Strict raw-event API schemas; client-computed features are never accepted."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

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
    device_id: Identifier
    session_id: Identifier
    card_reference: Identifier
    card_bin: Annotated[str, Field(strict=True, pattern=r"^\d{6,8}$")]
    ip_reference: Identifier
    amount: Amount
    currency: Literal["USD", "INR"]
    timestamp: datetime
    event_sequence: EventSequence
    campaign_active: Annotated[bool, Field(strict=True)]

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
    decline_reason: (
        Literal["generic_decline", "insufficient_funds", "do_not_honor"] | None
    ) = None

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
    risk_score: float
    rule_score: int
    reason_codes: list[str]
    model_version: str
    policy_version: str
    device_state_version: int
    idempotent_replay: bool
    processed_at: datetime
    latency_ms: float


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
