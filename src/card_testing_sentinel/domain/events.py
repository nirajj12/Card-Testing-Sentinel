"""Internal lifecycle event -- the normalised form of an API request.

Three types:
  * ``authorization_request``  -- scored before the merchant creates a
    Razorpay order. Merchant-visible facts only; never card / method / result.
  * ``authorization_outcome``  -- a *verified* Razorpay result. May carry the
    card / method metadata Razorpay reports afterwards; historical only.
  * ``checkout_completion``    -- an approved payment that finished.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

EventType = Literal[
    "authorization_request", "authorization_outcome", "checkout_completion"
]

PaymentMethod = Literal["card", "upi", "netbanking", "wallet"]
CardNetwork = Literal["visa", "mastercard", "amex", "rupay", "diners", "other"]
CardType = Literal["credit", "debit", "prepaid", "unknown"]
FailureReason = Literal[
    "generic_decline",
    "insufficient_funds",
    "do_not_honor",
    "card_declined",
    "authentication_failed",
    "international_blocked",
]


class EventContractError(ValueError):
    pass


class ConflictingDuplicateError(EventContractError):
    pass


class LifecycleEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    request_id: str | None = None
    event_sequence: int
    timestamp: datetime
    event_type: EventType
    merchant_id: str | None = None
    customer_id: str | None = None
    device_id: str
    session_id: str
    ip_fingerprint: str | None = None
    amount: float | None = None
    currency: str | None = None
    campaign_active: bool | None = None
    # verified-outcome-only metadata -- never present on a request
    authorization_result: Literal["approved", "declined"] | None = None
    failure_reason: FailureReason | None = None
    payment_method: PaymentMethod | None = None
    card_last4: str | None = None
    card_network: CardNetwork | None = None
    card_type: CardType | None = None
    card_issuer: str | None = None
    international: bool | None = None

    @field_validator("timestamp")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must include an explicit timezone")
        return value

    @field_validator("amount")
    @classmethod
    def valid_amount(cls, value: float | None) -> float | None:
        if value is not None and (value <= 0 or value != value):
            raise ValueError("amount must be finite and positive")
        return value

    @field_validator("event_sequence")
    @classmethod
    def sequence_is_nonnegative(cls, value: int) -> int:
        if isinstance(value, bool) or value < 0:
            raise ValueError("event_sequence must be a non-negative integer")
        return value

    @model_validator(mode="after")
    def lifecycle_fields(self):
        outcome_only = (
            self.authorization_result,
            self.failure_reason,
            self.payment_method,
            self.card_last4,
            self.card_network,
            self.card_type,
            self.card_issuer,
            self.international,
        )
        if self.event_type == "authorization_request":
            if self.request_id is None or self.merchant_id is None:
                raise ValueError("request needs request_id and merchant_id")
            if any(value is None for value in (self.amount, self.currency)):
                raise ValueError("request needs amount and currency")
            if any(value is not None for value in outcome_only):
                raise ValueError("request cannot carry outcome or card metadata")
        elif self.event_type == "authorization_outcome":
            if self.request_id is None or self.authorization_result is None:
                raise ValueError("outcome needs request_id and authorization_result")
            if self.authorization_result == "approved" and self.failure_reason:
                raise ValueError("an approval cannot carry a failure reason")
        elif self.request_id is None:
            raise ValueError("checkout completion needs the approved request_id")
        return self
