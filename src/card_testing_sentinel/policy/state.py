"""Decision record for the policy layer."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Literal

Action = Literal["allow", "review", "block"]


@dataclass(frozen=True)
class PolicyDecision:
    action: Action
    reason_codes: tuple[str, ...]
    rule_score: int
    #: null only in the degraded failover, when no model could be loaded.
    risk_score: float | None = None
    #: Policy TTL metadata set when action == "block". The runtime blocks the
    #: current attempt only; it does not persist a device ban until this time.
    #: Every later request is independently scored from then-current history.
    block_expires_at: datetime | None = None

    def to_dict(self) -> dict:
        return asdict(self)
