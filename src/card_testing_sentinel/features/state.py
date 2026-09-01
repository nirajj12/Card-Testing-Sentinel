"""Per-device runtime state used to build causal features.

A pending request carries only what the merchant knew when it asked for a
decision -- no card, no method, no outcome. Card / method metadata appears
only on ``ProcessedPayment``, which is created later from a *verified*
Razorpay outcome and therefore only ever influences a *future* request.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class RequestMark:
    """A committed request, kept for velocity / amount history."""

    timestamp: datetime
    event_sequence: int
    session_id: str
    ip: str
    amount: float


@dataclass(frozen=True)
class PendingRequest:
    """A scored request awaiting its verified outcome. Precheck-known only."""

    request_id: str
    event_id: str
    timestamp: datetime
    event_sequence: int
    device_id: str
    session_id: str
    ip: str
    amount: float
    blocked: bool


@dataclass(frozen=True)
class ProcessedPayment:
    """A request whose outcome has been verified. Carries the card / method
    metadata Razorpay reports *after* the attempt -- historical only."""

    request_id: str
    timestamp: datetime
    session_id: str
    ip: str
    amount: float
    approved: bool
    payment_method: str | None = None
    card_last4: str | None = None
    card_network: str | None = None
    card_type: str | None = None
    card_issuer: str | None = None
    international: bool | None = None


@dataclass
class DeviceState:
    processed: list[ProcessedPayment] = field(default_factory=list)
    requests: list[RequestMark] = field(default_factory=list)
    session_starts: dict[str, datetime] = field(default_factory=dict)
    checkout_times: list[datetime] = field(default_factory=list)
    decline_streak: int = 0
    state_version: int = 0
    first_request_at: datetime | None = None
    #: highest ``(timestamp, event_sequence)`` committed for THIS device.
    #: Ordering is enforced per device, not globally -- device B is never
    #: rejected because device A produced a later timestamp first.
    last_order: tuple[str, int] | None = None
