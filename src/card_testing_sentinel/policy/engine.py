"""Risk policy: turn a risk score into allow / review / temporary block.

The model estimates behaviour. The policy decides what friction a merchant
is willing to impose. Those are different jobs, and the thresholds live here
(and in the selected policy artifact), never inside the model.

Three families are supported so the choice between them is an evidence
question, settled on validation, rather than an architectural assumption:

* ``threshold``       -- score alone decides both bands.
* ``evidence_gated``  -- review on score; block additionally needs corroborating
  merchant-visible evidence.
* ``persistent``      -- review on score; block additionally needs the device to
  have been elevated more than once inside a recent window.

`review` is a decision state in this prototype. A production merchant could
map it to step-up verification, rate limiting, a delayed retry or a manual
queue; none of those are implemented here and none are claimed.

`block` is always temporary. It carries an expiry, nothing is permanently
labelled fraudulent, and a later request is scored from current history --
so a device whose behaviour changes returns to allow on its own.

``degraded_rules_only`` is a failover for a missing or unloadable model. It
uses the deterministic rule score only, never the validation-selected ML
thresholds, and is always surfaced in the reason codes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from card_testing_sentinel.policy.evidence import evidence_codes
from card_testing_sentinel.policy.reasons import REASON_CODES
from card_testing_sentinel.policy.rules import MAX_RULE_SCORE, evaluate_rules
from card_testing_sentinel.policy.state import PolicyDecision

FAMILIES = ("threshold", "evidence_gated", "persistent")


@dataclass
class DeviceRiskHistory:
    """The minimal state a persistent policy needs: recent elevated scores.

    Only (timestamp, score) pairs inside the window are kept, and the list is
    capped, so this can never grow into a prediction store.
    """

    recent: list[tuple[str, float]] = field(default_factory=list)

    def record(
        self, timestamp: datetime, score: float, window: timedelta, cap: int
    ) -> None:
        self.recent.append((timestamp.isoformat(), float(score)))
        self.prune(timestamp, window, cap)

    def prune(self, now: datetime, window: timedelta, cap: int) -> None:
        boundary = now - window
        self.recent = [
            row
            for row in self.recent[-cap:]
            if datetime.fromisoformat(row[0]) >= boundary
        ]

    def elevated_count(self, now: datetime, threshold: float, window: timedelta) -> int:
        boundary = now - window
        return sum(
            1
            for stamp, score in self.recent
            if score >= threshold and datetime.fromisoformat(stamp) >= boundary
        )


class RiskPolicy:
    def __init__(self, config: dict):
        self.family = str(config["family"])
        if self.family not in FAMILIES:
            raise ValueError(f"unknown policy family: {self.family}")
        self.review_threshold = float(config["review_threshold"])
        self.block_threshold = float(config["block_threshold"])
        self.block_evidence = int(config.get("block_evidence", 0))
        self.block_elevated_count = int(config.get("block_elevated_count", 1))
        self.persistence_window = timedelta(
            hours=float(config.get("persistence_window_hours", 24))
        )
        self.history_cap = int(config.get("history_cap", 16))
        self.block_ttl = timedelta(seconds=int(config["block_ttl_seconds"]))
        # Campaign tolerance: a genuine sale produces genuine bursts, so the
        # bands may be nudged up while the merchant is running one. Zero
        # unless validation showed it earns its place.
        self.campaign_review_increment = float(
            config.get("campaign_review_increment", 0.0)
        )
        self.campaign_block_increment = float(
            config.get("campaign_block_increment", 0.0)
        )
        # Degraded failover only -- never used while a model is available.
        self.degraded_review_rule_score = int(config["degraded_review_rule_score"])
        self.degraded_block_rule_score = int(config["degraded_block_rule_score"])

        if not 0.0 <= self.review_threshold <= self.block_threshold <= 1.0:
            raise ValueError("risk thresholds must satisfy 0 <= review <= block <= 1")
        if not (
            0
            <= self.degraded_review_rule_score
            <= self.degraded_block_rule_score
            <= MAX_RULE_SCORE
        ):
            raise ValueError("degraded rule thresholds are out of range")

    @property
    def campaign_aware(self) -> bool:
        return bool(self.campaign_review_increment or self.campaign_block_increment)

    # -- decision ----------------------------------------------------------

    def decide(
        self,
        *,
        snapshot: dict,
        risk_score: float | None,
        timestamp: datetime,
        campaign_active: bool = False,
        history: DeviceRiskHistory | None = None,
    ) -> PolicyDecision:
        """`campaign_active` is a merchant fact carried on the request, not a
        model feature -- the policy is told it explicitly rather than reading
        it out of the causal snapshot."""
        rule_score, _fired = evaluate_rules(snapshot)
        if risk_score is None:
            return self._degraded(rule_score)

        campaign = bool(campaign_active)
        review_at = self.review_threshold + (
            self.campaign_review_increment if campaign else 0.0
        )
        block_at = self.block_threshold + (
            self.campaign_block_increment if campaign else 0.0
        )

        evidence = evidence_codes(snapshot)
        reasons: list[str] = []
        action = "allow"

        if risk_score >= block_at and self._block_allowed(evidence, history, timestamp):
            action = "block"
            reasons.append("elevated_model_risk")
            reasons.extend(evidence)
            if self.family == "persistent":
                reasons.append("persistent_elevated_risk")
        elif risk_score >= review_at:
            action = "review"
            reasons.append("elevated_model_risk")
            reasons.extend(evidence)

        if campaign and action != "allow" and self.campaign_aware:
            reasons.append("campaign_tolerance_applied")

        reasons = list(dict.fromkeys(reasons))
        if any(code not in REASON_CODES for code in reasons):
            raise RuntimeError("policy emitted an uncontracted reason code")
        return PolicyDecision(
            action=action,
            reason_codes=tuple(reasons),
            rule_score=rule_score,
            risk_score=risk_score,
            block_expires_at=(
                timestamp + self.block_ttl if action == "block" else None
            ),
        )

    def _block_allowed(
        self,
        evidence: list[str],
        history: DeviceRiskHistory | None,
        timestamp: datetime,
    ) -> bool:
        if self.family == "threshold":
            return True
        if self.family == "evidence_gated":
            return len(evidence) >= self.block_evidence
        # persistent: this attempt plus prior elevated attempts in the window
        prior = (
            history.elevated_count(
                timestamp, self.review_threshold, self.persistence_window
            )
            if history is not None
            else 0
        )
        return (prior + 1) >= self.block_elevated_count and len(
            evidence
        ) >= self.block_evidence

    def _degraded(self, rule_score: int) -> PolicyDecision:
        if rule_score >= self.degraded_block_rule_score:
            action = "block"
        elif rule_score >= self.degraded_review_rule_score:
            action = "review"
        else:
            action = "allow"
        return PolicyDecision(
            action=action,
            reason_codes=("degraded_rules_only",),
            rule_score=rule_score,
            risk_score=None,
            block_expires_at=None,
        )
