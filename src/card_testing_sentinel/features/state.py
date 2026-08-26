from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class ProcessedAuthorization:
    request_id: str
    timestamp: datetime
    session_id: str
    ip_fingerprint: str
    card_fingerprint: str
    card_bin: str
    amount: float
    approved: bool


@dataclass
class DeviceState:
    processed: list[ProcessedAuthorization] = field(default_factory=list)
    request_times: list[tuple[datetime, int]] = field(default_factory=list)
    session_starts: dict[str, datetime] = field(default_factory=dict)
    checkout_times: list[datetime] = field(default_factory=list)
    decline_streak: int = 0
    state_version: int = 0


@dataclass(frozen=True)
class PendingRequest:
    event_id: str
    request_id: str
    timestamp: datetime
    event_sequence: int
    device_id: str
    session_id: str
    ip_fingerprint: str
    card_fingerprint: str
    card_bin: str
    amount: float
    blocked: bool
