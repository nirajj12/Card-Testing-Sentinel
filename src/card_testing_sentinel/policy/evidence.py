"""Corroborating evidence for a block.

A block stops a real customer from paying, so it should not rest on one
model score alone. These signals are the merchant-visible facts that make a
high score *believable*: the device has already failed repeatedly, is
churning sessions or IPs, or is hammering retries.

Each signal is a plain threshold on a contract feature, so a blocked
customer can be told exactly which observable behaviour supported the
decision. Nothing here uses the current attempt's card, method or outcome.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EvidenceSignal:
    reason_code: str
    description: str


#: (signal, predicate) pairs. Kept deliberately small and readable.
EVIDENCE_SIGNALS: tuple[tuple[EvidenceSignal, str], ...] = (
    (
        EvidenceSignal(
            "repeated_verified_failures", "Two or more verified declines in 24h."
        ),
        "recent_failures_24h",
    ),
    (
        EvidenceSignal("verified_decline_streak", "Two or more consecutive declines."),
        "decline_streak",
    ),
    (
        EvidenceSignal("multi_session_persistence", "Three or more sessions in 24h."),
        "sessions_24h",
    ),
    (
        EvidenceSignal("ip_rotation_evidence", "The device changed IP within 24h."),
        "ip_changes_24h",
    ),
    (
        EvidenceSignal("sustained_request_burst", "Five or more requests in 24h."),
        "requests_24h",
    ),
    (
        EvidenceSignal(
            "rapid_retry_after_decline", "Most declines were retried at speed."
        ),
        "retry_after_decline_ratio_24h",
    ),
)

_MINIMUMS = {
    "recent_failures_24h": 2.0,
    "decline_streak": 2.0,
    "sessions_24h": 3.0,
    "ip_changes_24h": 1.0,
    "requests_24h": 5.0,
    "retry_after_decline_ratio_24h": 0.5,
}


def evidence_codes(snapshot: dict) -> list[str]:
    """Which corroborating signals the snapshot supports."""
    fired = []
    for signal, feature in EVIDENCE_SIGNALS:
        if float(snapshot.get(feature, 0.0)) >= _MINIMUMS[feature]:
            fired.append(signal.reason_code)
    # `rapid_retry_after_decline` is meaningless without declines to retry.
    if (
        "rapid_retry_after_decline" in fired
        and float(snapshot.get("recent_failures_24h", 0.0)) < 2.0
    ):
        fired.remove("rapid_retry_after_decline")
    return fired


def evidence_count(snapshot: dict) -> int:
    return len(evidence_codes(snapshot))
