"""Corroborating evidence and historical trust for Policy v2.

A block stops a real customer from paying, so it should never rest on one
model score. These are the merchant-visible facts that make a high score
*believable*, and -- new in v2 -- the facts that make it doubtful.

Three design rules, all of them consequences of earlier phases:

* **Missing customer identity is never evidence.** `customer_id_present == 0`
  is not a signal and must not appear here: absent identity means
  information is unavailable, not that the payer is abusive.
* **Device count alone is never evidence.** Dataset v3 deliberately contains
  legitimate customers with two or three devices, so
  `customer_distinct_devices_7d >= 2` only counts when it is paired with
  failures on that account.
* **Trust withholds a block, it never grants one.** Suppression can only turn
  a block into a review; it can never turn a review into an allow.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Signal:
    reason_code: str
    description: str


def _at_least(snapshot: dict, feature: str, minimum: float) -> bool:
    return float(snapshot.get(feature, 0.0)) >= minimum


# --------------------------------------------------------------------------
# evidence
# --------------------------------------------------------------------------

#: The v1 signals, unchanged, so a v1-to-v2 comparison is like-for-like.
V1_SIGNALS: tuple[tuple[Signal, str, float], ...] = (
    (
        Signal("repeated_verified_failures", "Two or more verified declines in 24h."),
        "recent_failures_24h",
        2.0,
    ),
    (
        Signal("verified_decline_streak", "Two or more consecutive declines."),
        "decline_streak",
        2.0,
    ),
    (
        Signal("multi_session_persistence", "Three or more sessions in 24h."),
        "sessions_24h",
        3.0,
    ),
    (
        Signal("ip_rotation_evidence", "The device changed IP within 24h."),
        "ip_changes_24h",
        1.0,
    ),
    (
        Signal("sustained_request_burst", "Five or more requests in 24h."),
        "requests_24h",
        5.0,
    ),
    (
        Signal("rapid_retry_after_decline", "Most declines were retried at speed."),
        "retry_after_decline_ratio_24h",
        0.5,
    ),
)

#: Longer horizons, so a patient actor whose 24h counters always reset can
#: still accumulate corroboration. This is the gap Blind v1.1 exposed:
#: `requests_24h >= 5` was structurally unreachable for the patient families,
#: so the gate could never authorise a block on exactly the behaviour we most
#: wanted to stop.
LONG_HORIZON_SIGNALS: tuple[tuple[Signal, str, float], ...] = (
    (
        Signal("sustained_failures_7d", "Three or more verified declines in 7 days."),
        "failures_7d",
        3.0,
    ),
    (
        Signal("multi_day_activity_7d", "Active on three or more days in 7 days."),
        "active_day_count_7d",
        3.0,
    ),
    (
        Signal("sustained_requests_7d", "Six or more requests in 7 days."),
        "requests_7d",
        6.0,
    ),
    (
        Signal("irregular_cadence", "Highly irregular gaps between attempts."),
        "gap_variability",
        1.5,
    ),
)

#: Account-level corroboration. `account_device_spread_with_failures` is the
#: only place device count appears, and it is conjunctive by construction.
CUSTOMER_SIGNALS: tuple[Signal, ...] = (
    Signal(
        "account_failures_across_devices",
        "Two or more account declines in 7 days.",
    ),
    Signal(
        "account_device_spread_with_failures",
        "The account used several devices AND failed on them.",
    ),
)

EVIDENCE_SETS = ("v1_like", "v2_long_horizon", "v2_full")


def evidence_codes_v2(snapshot: dict, evidence_set: str) -> list[str]:
    """Which corroborating signals this snapshot supports."""
    if evidence_set not in EVIDENCE_SETS:
        raise ValueError(f"unknown evidence set: {evidence_set}")

    fired = [
        signal.reason_code
        for signal, feature, minimum in V1_SIGNALS
        if _at_least(snapshot, feature, minimum)
    ]
    # `rapid_retry_after_decline` is meaningless without declines to retry.
    if "rapid_retry_after_decline" in fired and not _at_least(
        snapshot, "recent_failures_24h", 2.0
    ):
        fired.remove("rapid_retry_after_decline")
    if evidence_set == "v1_like":
        return fired

    fired.extend(
        signal.reason_code
        for signal, feature, minimum in LONG_HORIZON_SIGNALS
        if _at_least(snapshot, feature, minimum)
    )
    if evidence_set == "v2_long_horizon":
        return fired

    if _at_least(snapshot, "customer_failures_7d", 2.0):
        fired.append("account_failures_across_devices")
    # Device spread ONLY counts alongside failures on that account: Dataset v3
    # contains legitimate two- and three-device customers on purpose.
    if _at_least(snapshot, "customer_distinct_devices_7d", 2.0) and _at_least(
        snapshot, "customer_failures_7d", 1.0
    ):
        fired.append("account_device_spread_with_failures")
    return fired


# --------------------------------------------------------------------------
# historical trust
# --------------------------------------------------------------------------

TRUST_LEVELS = ("none", "moderate", "strong")

#: (level -> (reason, feature, minimum)). Tenure is preferred over raw
#: success count: an account that is weeks old is far more expensive for an
#: attacker to fake than four recent checkouts, and Blind v1.1 showed
#: `warm_up_then_test` buying exactly that kind of credit.
_TRUST_RULES = {
    "moderate": (
        ("established_account_history", "customer_age_seconds", 14 * 86400.0),
        ("recent_successful_payments", "customer_successful_checkouts_30d", 3.0),
    ),
    "strong": (
        ("established_account_history", "customer_age_seconds", 7 * 86400.0),
        ("recent_successful_payments", "customer_successful_checkouts_30d", 2.0),
        ("recent_successful_payments", "successful_checkouts_30d", 3.0),
    ),
}


def trust_codes(snapshot: dict, level: str) -> list[str]:
    """Signals that a block would probably be hitting a real customer.

    These never raise risk and never grant a block -- they can only withhold
    one, which keeps the failure mode on the side of letting a payment
    through rather than stopping a genuine one.
    """
    if level not in TRUST_LEVELS:
        raise ValueError(f"unknown trust level: {level}")
    if level == "none":
        return []
    fired: list[str] = []
    for reason, feature, minimum in _TRUST_RULES[level]:
        if _at_least(snapshot, feature, minimum) and reason not in fired:
            fired.append(reason)
    return fired
