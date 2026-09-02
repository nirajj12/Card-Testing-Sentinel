"""Risk policy v2: turn a Model v2 score into allow / review / temporary block.

The split is unchanged and deliberate. The model ranks risk; the policy
decides what friction the merchant is willing to impose. No business
threshold lives inside the model artifact.

Blocking stays evidence-gated. Blind v1.1 showed the gate withholding blocks
on 14 devices, 12 of them legitimate -- it earned its place off the
distribution it was chosen on, so v2 keeps the architecture and only widens
what counts as evidence.

Two things are new:

* **Long-horizon and account evidence.** v1's gate was five-sixths
  24h-windowed, and `requests_24h >= 5` was structurally unreachable for the
  patient families, so a block could never be authorised on exactly the
  behaviour we most wanted to stop.
* **Trust suppression.** Historical trust can turn a block into a review. It
  can never turn a review into an allow, and it never lowers the score.

`review` remains a decision state in this prototype: a merchant could map it
to step-up verification, rate limiting, a delayed retry or a manual queue.
None of those are implemented here and none are claimed -- Sentinel does not
issue OTP, 3DS or issuer actions.

`block` applies to the current attempt. Nothing is permanently labelled
fraudulent: every later request is scored again from its then-current history.
The configured TTL is returned as policy metadata; this runtime does not
persist or enforce a device ban until that timestamp.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from card_testing_sentinel.policy.evidence_v2 import (
    EVIDENCE_SETS,
    TRUST_LEVELS,
    evidence_codes_v2,
    trust_codes,
)
from card_testing_sentinel.policy.reasons_v2 import REASON_CODES_V2
from card_testing_sentinel.policy.rules import MAX_RULE_SCORE, evaluate_rules
from card_testing_sentinel.policy.state import PolicyDecision

FAMILY = "evidence_gated_v2"


class RiskPolicyV2:
    def __init__(self, config: dict):
        self.family = str(config.get("family", FAMILY))
        if self.family != FAMILY:
            raise ValueError(f"unknown policy family: {self.family}")
        self.review_threshold = float(config["review_threshold"])
        self.block_threshold = float(config["block_threshold"])
        self.block_evidence = int(config["block_evidence"])
        self.evidence_set = str(config["evidence_set"])
        if self.evidence_set not in EVIDENCE_SETS:
            raise ValueError(f"unknown evidence set: {self.evidence_set}")
        self.trust_suppression = str(config["trust_suppression"])
        if self.trust_suppression not in TRUST_LEVELS:
            raise ValueError(f"unknown trust level: {self.trust_suppression}")
        self.block_ttl = timedelta(seconds=int(config["block_ttl_seconds"]))
        self.campaign_review_increment = float(
            config.get("campaign_review_increment", 0.0)
        )
        self.campaign_block_increment = float(
            config.get("campaign_block_increment", 0.0)
        )
        self.degraded_review_rule_score = int(config["degraded_review_rule_score"])
        self.degraded_block_rule_score = int(config["degraded_block_rule_score"])

        if not 0.0 <= self.review_threshold <= self.block_threshold <= 1.0:
            raise ValueError("risk thresholds must satisfy 0 <= review <= block <= 1")
        if self.block_evidence < 0:
            raise ValueError("block_evidence must not be negative")
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
    ) -> PolicyDecision:
        """`campaign_active` is a merchant fact carried on the request, not a
        model feature -- the policy is told it explicitly."""
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

        evidence = evidence_codes_v2(snapshot, self.evidence_set)
        trust = trust_codes(snapshot, self.trust_suppression)
        reasons: list[str] = []
        action = "allow"

        if risk_score >= block_at:
            if len(evidence) < self.block_evidence:
                action = "review"
                reasons.append("elevated_model_risk")
                reasons.extend(evidence)
                reasons.append("block_withheld_insufficient_evidence")
            elif trust:
                # Trust can only soften a block into a review -- never into an
                # allow, and never by touching the score.
                action = "review"
                reasons.append("elevated_model_risk")
                reasons.extend(evidence)
                reasons.extend(trust)
                reasons.append("block_withheld_established_history")
            else:
                action = "block"
                reasons.append("elevated_model_risk")
                reasons.extend(evidence)
        elif risk_score >= review_at:
            action = "review"
            reasons.append("elevated_model_risk")
            reasons.extend(evidence)

        if campaign and action != "allow" and self.campaign_aware:
            reasons.append("campaign_tolerance_applied")

        reasons = list(dict.fromkeys(reasons))
        if any(code not in REASON_CODES_V2 for code in reasons):
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

    def _degraded(self, rule_score: int) -> PolicyDecision:
        """Failover only, when no usable model artifact could be loaded.

        Never uses the validation-selected ML thresholds, and is always
        surfaced in the reason codes so a degraded decision can never be
        mistaken for a normal one.
        """
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
