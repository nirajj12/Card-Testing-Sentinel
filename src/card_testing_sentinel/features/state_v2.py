"""Runtime state for FeatureEngine v2: per device AND per customer.

v1 held device state only. v2 adds a customer entity, because the behaviour
that defeated Model v1 -- one campaign spread thinly across several devices --
is invisible to any device-scoped counter.

A customer is keyed by a one-way digest, never the raw identifier. The state
holds timestamps and device digests only: no amounts, no card metadata, no
identifiers that could be read back out.

Both entities are bounded. Lists are pruned to the longest window any feature
needs and additionally capped, so state cannot grow without limit on a device
or account that transacts forever.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta

# Re-exported so v2 shares v1's event-shaped records exactly.
from card_testing_sentinel.features.state import (
    ProcessedPayment,
    RequestMark,
)

__all__ = [
    "CustomerState",
    "DeviceStateV2",
    "PendingRequestV2",
    "ProcessedPayment",
    "RequestMark",
    "customer_key",
]


def customer_key(value: str | None) -> str | None:
    """A one-way digest of a customer identity.

    The engine never stores the raw value: state is keyed by this digest, so
    a memory dump or a state export cannot recover who the customer was. The
    API layer already HMAC-protects identifiers before they reach the engine;
    this is the second, unconditional layer.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return hashlib.blake2s(f"customer:{text}".encode(), digest_size=16).hexdigest()


@dataclass(frozen=True)
class PendingRequestV2:
    """A scored request awaiting its verified outcome. Precheck-known only.

    Carries the customer digest so the later outcome can be attributed to the
    right account: outcome events do not repeat the customer identity.
    """

    request_id: str
    event_id: str
    timestamp: datetime
    event_sequence: int
    device_id: str
    session_id: str
    ip: str
    amount: float
    customer_key: str | None
    blocked: bool


@dataclass
class DeviceStateV2:
    processed: list[ProcessedPayment] = field(default_factory=list)
    requests: list[RequestMark] = field(default_factory=list)
    session_starts: dict[str, datetime] = field(default_factory=dict)
    checkout_times: list[datetime] = field(default_factory=list)
    decline_streak: int = 0
    state_version: int = 0
    first_request_at: datetime | None = None
    #: highest ``(timestamp, event_sequence)`` committed for THIS device.
    last_order: tuple[str, int] | None = None

    def prune(self, now: datetime, window: timedelta, caps: dict) -> None:
        boundary = now - window
        self.requests = [
            mark
            for mark in self.requests[-int(caps["max_device_requests"]) :]
            if mark.timestamp >= boundary
        ]
        self.processed = [
            payment
            for payment in self.processed[-int(caps["max_device_payments"]) :]
            if payment.timestamp >= boundary
        ]
        self.checkout_times = [
            stamp
            for stamp in self.checkout_times[-int(caps["max_device_payments"]) :]
            if stamp >= boundary
        ]
        self.session_starts = {
            session: start
            for session, start in self.session_starts.items()
            if start >= boundary
        }


@dataclass
class CustomerState:
    """One account's behaviour across every device it has used.

    ``devices`` holds ``(timestamp, device digest, order)`` for prior
    requests, so a snapshot can count distinct devices strictly before the
    current event without re-reading the raw stream.
    """

    devices: list[tuple[datetime, str, tuple[str, int]]] = field(default_factory=list)
    failures: list[datetime] = field(default_factory=list)
    checkouts: list[datetime] = field(default_factory=list)
    first_seen: datetime | None = None
    #: highest ``(timestamp, event_sequence)`` committed for THIS customer,
    #: across all of its devices.
    last_order: tuple[str, int] | None = None

    def prune(self, now: datetime, window: timedelta, cap: int) -> None:
        boundary = now - window
        self.devices = [row for row in self.devices[-cap:] if row[0] >= boundary]
        self.failures = [stamp for stamp in self.failures[-cap:] if stamp >= boundary]
        self.checkouts = [stamp for stamp in self.checkouts[-cap:] if stamp >= boundary]
