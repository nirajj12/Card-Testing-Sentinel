from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

EventType = Literal[
    "authorization_request", "authorization_outcome", "checkout_completion"
]


class EventContractError(ValueError):
    pass


class ConflictingDuplicateError(EventContractError):
    pass


class LateEventError(EventContractError):
    pass


class LifecycleEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    request_id: str | None = None
    event_sequence: int
    timestamp: datetime
    event_type: EventType
    device_id: str
    session_id: str
    ip_fingerprint: str | None = None
    card_fingerprint: str | None = None
    card_bin: str | None = None
    amount: float | None = None
    currency: str | None = None
    campaign_active: bool | None = None
    authorization_result: Literal["approved", "declined"] | None = None
    decline_reason: str | None = None

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
    def sequence_is_integer(cls, value: int) -> int:
        if isinstance(value, bool) or value < 0:
            raise ValueError("event_sequence must be a nonnegative integer")
        return value

    @model_validator(mode="after")
    def lifecycle_fields(self):
        request_fields = (
            self.request_id,
            self.ip_fingerprint,
            self.card_fingerprint,
            self.card_bin,
            self.amount,
            self.currency,
            self.campaign_active,
        )
        if self.event_type == "authorization_request":
            if any(value is None for value in request_fields):
                raise ValueError("authorization request fields are required")
            if self.authorization_result is not None or self.decline_reason is not None:
                raise ValueError("request cannot contain future outcome fields")
        elif self.event_type == "authorization_outcome":
            if self.request_id is None or self.authorization_result is None:
                raise ValueError("outcome requires request_id and result")
            if (
                self.authorization_result == "approved"
                and self.decline_reason is not None
            ):
                raise ValueError("approval cannot have a decline reason")
        elif self.request_id is None:
            raise ValueError("completion requires the approved request_id")
        return self
