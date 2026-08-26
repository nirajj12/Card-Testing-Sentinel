"""Deterministic, serializable per-device evidence accumulation policy."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

from card_testing_sentinel.policy.reasons import REASON_CODES
from card_testing_sentinel.policy.rules import evaluate_rules
from card_testing_sentinel.policy.state import Action, PolicyDecision, PolicyState


class OperationalPolicy:
    """Apply one candidate to isolated per-device state.

    Risk is a decayed sum of calibrated risk scores. Scores are retained only
    for the declared high-risk window. Successful-checkout history and stable
    same-card/amount retries attenuate existing risk; neither can allowlist a
    device or erase the current score. Campaign requests raise thresholds and
    evidence requirements. A block requires repeated risk, which is itself a
    causal corroborating signal; long-term candidates additionally require
    card, session, IP, switch, or rule evidence.
    """

    def __init__(self, candidate: dict):
        self.candidate = dict(candidate)
        self.states: dict[str, PolicyState] = {}

    def state_for(self, device_id: str) -> PolicyState:
        return self.states.setdefault(device_id, PolicyState())

    @staticmethod
    def _event_digest(
        event_id: str,
        timestamp: datetime,
        session_id: str,
        risk_score: float,
        snapshot: dict,
    ) -> str:
        safe = {
            "event_id": event_id,
            "timestamp": timestamp.isoformat(),
            "session_id": session_id,
            "risk_score": float(risk_score),
            "features": {
                name: snapshot.get(name)
                for name in (
                    "campaign_active",
                    "prior_successful_checkouts",
                    "same_card_retry_ratio_24h",
                    "amount_delta_from_previous",
                    "distinct_cards_14d",
                    "card_switches_after_decline_24h",
                    "sessions_7d",
                    "cross_session_cards_7d",
                    "ip_changes_24h",
                )
            },
        }
        return hashlib.sha256(
            json.dumps(safe, sort_keys=True, default=str).encode()
        ).hexdigest()

    def decide(
        self,
        *,
        device_id: str,
        event_id: str,
        timestamp: datetime,
        session_id: str,
        risk_score: float,
        snapshot: dict,
    ) -> PolicyDecision:
        if not 0.0 <= risk_score <= 1.0:
            raise ValueError("calibrated risk_score must be in [0, 1]")
        state = self.state_for(device_id)
        digest = self._event_digest(
            event_id, timestamp, session_id, risk_score, snapshot
        )
        if event_id in state.event_digests:
            if state.event_digests[event_id] != digest:
                raise ValueError("conflicting retry for an existing policy event")
            return PolicyDecision(**state.decisions_by_event[event_id])
        if state.last_timestamp is not None:
            previous = datetime.fromisoformat(state.last_timestamp)
            if timestamp < previous:
                raise ValueError("late policy event refused")
            elapsed_hours = (timestamp - previous).total_seconds() / 3600.0
            half_life = float(self.candidate["half_life_hours"])
            state.accumulated_risk *= 0.5 ** (elapsed_hours / half_life)

        reasons: list[str] = []
        successful = int(snapshot.get("prior_successful_checkouts", 0))
        if successful > state.last_successful_checkout_count:
            state.accumulated_risk *= float(self.candidate["checkout_risk_multiplier"])
            if self.candidate["family"] == "checkout_protected":
                state.checkout_protection_remaining = 3
            reasons.append("successful_checkout_risk_reduction")
        state.last_successful_checkout_count = max(
            state.last_successful_checkout_count, successful
        )
        stable_retry = (
            float(snapshot.get("same_card_retry_ratio_24h", 0.0)) >= 0.75
            and abs(float(snapshot.get("amount_delta_from_previous", 0.0))) <= 2.0
            and int(snapshot.get("prior_attempts_24h", 0)) >= 1
        )
        if stable_retry:
            state.accumulated_risk *= float(
                self.candidate["stable_retry_risk_multiplier"]
            )
            reasons.append("stable_retry_risk_reduction")

        effective_risk_score = float(risk_score)
        if (
            self.candidate["family"] == "checkout_protected"
            and state.checkout_protection_remaining > 0
        ):
            effective_risk_score *= float(self.candidate["checkout_risk_multiplier"])
            state.checkout_protection_remaining -= 1
        state.accumulated_risk += effective_risk_score
        state.last_timestamp = timestamp.isoformat()
        state.request_count += 1
        if session_id not in state.sessions:
            state.sessions.append(session_id)
        review_threshold = float(self.candidate.get("review_threshold", 1.1))
        block_threshold = float(self.candidate.get("block_threshold", 1.1))
        increment = float(self.candidate.get("campaign_threshold_increment", 0))
        extra_evidence = int(self.candidate.get("campaign_extra_evidence", 0))
        if bool(snapshot.get("campaign_active", False)) and (
            increment > 0 or extra_evidence > 0
        ):
            review_threshold += increment
            block_threshold += increment
            reasons.append("campaign_threshold_adjustment")

        state.consecutive_review = (
            state.consecutive_review + 1
            if effective_risk_score >= review_threshold
            else 0
        )
        state.consecutive_strong = (
            state.consecutive_strong + 1
            if effective_risk_score >= block_threshold
            else 0
        )
        state.recent_scores.append((timestamp.isoformat(), effective_risk_score))
        boundary = (
            timestamp.timestamp() - float(self.candidate["high_window_hours"]) * 3600
        )
        state.recent_scores = [
            row
            for row in state.recent_scores[
                -int(self.candidate["recent_request_limit"]) :
            ]
            if datetime.fromisoformat(row[0]).timestamp() >= boundary
        ]
        review_high_count = sum(
            score >= review_threshold for _, score in state.recent_scores
        )
        block_high_count = sum(
            score >= block_threshold for _, score in state.recent_scores
        )

        rule_score, _rule_reasons = evaluate_rules(snapshot)
        evidence = self._evidence(snapshot, state, block_high_count, reasons)
        evidence_count = len(evidence)
        campaign_extra = (
            extra_evidence if bool(snapshot.get("campaign_active", False)) else 0
        )
        family = self.candidate["family"]
        if family == "rules_only":
            review_trigger = rule_score >= int(self.candidate["review_rule_score"])
            block_trigger = rule_score >= int(self.candidate["block_rule_score"])
        elif family == "consecutive_high":
            review_trigger = state.consecutive_review >= int(
                self.candidate["review_consecutive"]
            )
            block_trigger = state.consecutive_strong >= int(
                self.candidate["block_consecutive"]
            )
        elif family == "accumulated_decay":
            review_trigger = state.accumulated_risk >= float(
                self.candidate["review_accumulated"]
            )
            block_trigger = state.accumulated_risk >= float(
                self.candidate["block_accumulated"]
            )
        else:
            review_trigger = review_high_count >= int(
                self.candidate["review_high_count"]
            )
            block_trigger = block_high_count >= int(self.candidate["block_high_count"])
        review_evidence = int(self.candidate.get("review_evidence", 0))
        block_evidence = int(self.candidate.get("block_evidence", 0))
        review_trigger = review_trigger and evidence_count >= (
            review_evidence + campaign_extra
        )
        block_trigger = block_trigger and evidence_count >= (
            block_evidence + campaign_extra
        )

        rules_review = rule_score >= int(self.candidate["review_rule_score"])
        rules_block = rule_score >= int(self.candidate["block_rule_score"])
        if rules_block or block_trigger:
            action: Action = "block"
            reasons.append(
                "rule_corroborated_block"
                if rules_block
                else self._risk_reason(family, block=True)
            )
        elif rules_review or review_trigger:
            action = "review"
            reasons.append(
                "rule_corroborated_review"
                if rules_review
                else self._risk_reason(family, block=False)
            )
        else:
            action = "allow"
        selected_reasons = tuple(dict.fromkeys([*reasons, *evidence]))
        if any(reason not in REASON_CODES for reason in selected_reasons):
            raise RuntimeError("policy emitted an uncontracted reason code")
        decision = PolicyDecision(
            action=action,
            reason_codes=selected_reasons,
            risk_score=float(risk_score),
            rule_score=int(rule_score),
            accumulated_risk=float(state.accumulated_risk),
            high_risk_count=int(review_high_count),
            consecutive_high_count=int(state.consecutive_review),
            evidence_count=int(evidence_count),
        )
        state.event_digests[event_id] = digest
        state.decisions_by_event[event_id] = decision.to_dict()
        return decision

    @staticmethod
    def _risk_reason(family: str, *, block: bool) -> str:
        if family == "consecutive_high":
            return "consecutive_high_model_risk"
        if family == "accumulated_decay":
            return "accumulated_model_risk"
        return "persistent_high_model_risk"

    @staticmethod
    def _evidence(
        snapshot: dict,
        state: PolicyState,
        block_high_count: int,
        existing_reasons: list[str],
    ) -> list[str]:
        evidence = []
        if int(snapshot.get("distinct_cards_14d", 0)) >= 2:
            evidence.append("high_risk_with_card_diversity")
        if int(snapshot.get("card_switches_after_decline_24h", 0)) >= 1:
            evidence.append("high_risk_with_card_switching")
        if (
            int(snapshot.get("sessions_7d", 0)) >= 2
            and int(snapshot.get("cross_session_cards_7d", 0)) >= 2
        ):
            evidence.append("cross_session_card_diversity")
        if int(snapshot.get("ip_changes_24h", 0)) >= 1:
            evidence.append("high_risk_with_ip_rotation")
        if block_high_count >= 2:
            evidence.append("persistent_high_model_risk")
        return [
            code for code in dict.fromkeys(evidence) if code not in existing_reasons
        ]

    def serialize(self) -> str:
        payload = {
            "candidate": self.candidate,
            "states": {
                device_id: state.to_dict()
                for device_id, state in sorted(self.states.items())
            },
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    @classmethod
    def deserialize(cls, encoded: str) -> OperationalPolicy:
        payload = json.loads(encoded)
        policy = cls(payload["candidate"])
        policy.states = {
            device_id: PolicyState.from_dict(state)
            for device_id, state in payload["states"].items()
        }
        return policy
