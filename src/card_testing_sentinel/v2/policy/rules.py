from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    reason_code: str
    contribution: int
    rationale: str


RULES = (
    Rule("RAPID_REQUEST_VELOCITY", 2, "Four or more request-known attempts within 60 seconds."),
    Rule("PROCESSED_VELOCITY", 1, "Five or more processed attempts within five minutes."),
    Rule("CARD_DIVERSITY", 1, "Three or more distinct cards within 24 hours."),
    Rule("DECLINE_STREAK", 1, "At least two consecutive prior processor declines."),
    Rule("CARD_SWITCH_AFTER_DECLINE", 1, "A prior decline is followed by card switching."),
    Rule("MULTI_SESSION_PERSISTENCE", 2, "At least three sessions and four prior attempts over seven days."),
    Rule("SHARED_IP_INTENSITY", 1, "Eight or more request-known attempts on the IP within five minutes."),
    Rule("LOW_AMOUNT_WITH_DIVERSITY", 1, "Low-value behavior is supporting evidence only when cards vary."),
)
MAX_RULE_SCORE = sum(rule.contribution for rule in RULES)


def evaluate_rules(features: dict) -> tuple[int, list[str]]:
    conditions = (
        features["prospective_requests_60s"] >= 4,
        features["prior_attempts_5m"] >= 5,
        features["distinct_cards_24h"] >= 3,
        features["prior_decline_streak"] >= 2,
        features["card_switches_after_decline_24h"] >= 1,
        features["sessions_7d"] >= 3 and features["prior_attempts_7d"] >= 4,
        features["requests_per_ip_5m"] >= 8,
        features["near_minimum_ratio_24h"] >= 0.5 and features["distinct_cards_24h"] >= 2,
    )
    reasons = [rule.reason_code for rule, matched in zip(RULES, conditions, strict=True) if matched]
    score = sum(rule.contribution for rule, matched in zip(RULES, conditions, strict=True) if matched)
    return score, reasons
