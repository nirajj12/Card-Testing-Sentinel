"""Deterministic behavioural rules.

Every condition reads a feature that is available at decision time from
merchant-visible signals or verified history. Rules that required knowing
the current attempt's card were removed with the feature-contract change.

The score (0..10) is the whole decision in rules_only mode.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    reason_code: str
    weight: int
    rationale: str


RULES: tuple[Rule, ...] = (
    Rule("rapid_request_velocity", 2, "Four or more requests within 60 seconds."),
    Rule("sustained_request_burst", 1, "Six or more requests within five minutes."),
    Rule("verified_decline_streak", 1, "Two or more consecutive verified declines."),
    Rule(
        "rapid_retry_after_decline",
        1,
        "Most verified declines were retried within two minutes.",
    ),
    Rule(
        "multi_session_persistence",
        2,
        "Three or more sessions with sustained attempts over 24 hours.",
    ),
    Rule(
        "shared_ip_intensity",
        1,
        "Eight or more requests from this IP within five minutes.",
    ),
    Rule("low_amount_velocity", 1, "Repeated near-floor amounts at speed."),
    Rule(
        "historical_card_churn",
        1,
        "Several distinct cards seen across prior verified outcomes.",
    ),
)

MAX_RULE_SCORE = sum(rule.weight for rule in RULES)


def evaluate_rules(features: dict) -> tuple[int, list[str]]:
    conditions = (
        features["requests_60s"] >= 4,
        features["requests_5m"] >= 6,
        features["decline_streak"] >= 2,
        features["retry_after_decline_ratio_24h"] >= 0.5
        and features["recent_failures_24h"] >= 2,
        features["sessions_24h"] >= 3 and features["requests_24h"] >= 4,
        features["requests_per_ip_5m"] >= 8,
        features["low_amount_ratio_24h"] >= 0.5 and features["requests_5m"] >= 3,
        features["distinct_card_last4_7d"] >= 3
        or features["card_change_after_decline_7d"] >= 1,
    )
    fired = [rule for rule, matched in zip(RULES, conditions, strict=True) if matched]
    return sum(rule.weight for rule in fired), [rule.reason_code for rule in fired]
