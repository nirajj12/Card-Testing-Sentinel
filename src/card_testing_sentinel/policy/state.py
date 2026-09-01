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
    #: set when action == "block". A block is always temporary: after this
    #: moment a later request is scored from current history, and nothing is
    #: permanently labelled fraudulent.
    block_expires_at: datetime | None = None

    def to_dict(self) -> dict:
        return asdict(self)
