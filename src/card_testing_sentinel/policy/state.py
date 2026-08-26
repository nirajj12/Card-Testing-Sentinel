"""Serializable state and decision records for the operational policy."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

Action = Literal["allow", "review", "block"]


@dataclass
class PolicyDecision:
    action: Action
    reason_codes: tuple[str, ...]
    risk_score: float
    rule_score: int
    accumulated_risk: float
    high_risk_count: int
    consecutive_high_count: int
    evidence_count: int

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PolicyState:
    """Policy-only state without labels, outcomes or scenario metadata."""

    schema_version: str = "operational-policy-state-1"
    last_timestamp: str | None = None
    request_count: int = 0
    accumulated_risk: float = 0.0
    recent_scores: list[tuple[str, float]] = field(default_factory=list)
    consecutive_review: int = 0
    consecutive_strong: int = 0
    sessions: list[str] = field(default_factory=list)
    last_successful_checkout_count: int = 0
    checkout_protection_remaining: int = 0
    decisions_by_event: dict[str, dict] = field(default_factory=dict)
    event_digests: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict) -> PolicyState:
        if payload.get("schema_version") != "operational-policy-state-1":
            raise ValueError("unsupported operational policy-state schema")
        restored = dict(payload)
        restored["recent_scores"] = [tuple(row) for row in payload["recent_scores"]]
        return cls(**restored)
