"""Deterministic, scenario-specific raw-event generation for the live demo.

Each scenario is a fixed, hand-authored sequence of attempts -- no
randomness, no wall-clock reads, no scenario label anywhere near the
generated identifiers. Everything here is data: identity suffixes, timing
gaps, amounts and an honest processor-outcome guess for each attempt. The
caller (``services.demo.DemoManager``) is responsible for turning a plan
into real, uniquely-namespaced ``PrecheckRequest``/``OutcomeRequest``/
``CheckoutRequest`` payloads and driving them through the real
``FraudDetectionService`` -- nothing here ever touches scoring, policy or
persistence, and nothing here encodes an expected allow/review/block
outcome. What the real engine decides for a given plan is discovered by
running it, not declared up front.

Per-scenario identity behavior (Stage 3):

* ``normal_customer`` / ``normal_bad_luck`` / ``flash_standard`` -- retain
  device, card, session and IP identity; ``normal_bad_luck`` allows a single
  card+IP switch (limited diversity, not attacker-style rotation).
* ``flash_hard_retry`` -- mainly retries the same card/session, with one
  backup-card switch late in the run after repeated processor timeouts.
* ``burst_attacker`` -- one device/session/short-lived IP block, a new card
  almost every attempt, seconds-scale gaps.
* ``evasive_attacker`` -- rotates card/session/IP in blocks of a few
  attempts rather than every attempt, with irregular short/long gaps.
* ``patient_attacker`` -- a new session on every attempt, a slower card/IP
  cadence, and hours-scale gaps between attempts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

AuthorizationResult = Literal["approved", "declined"]
DeclineReason = Literal["generic_decline", "insufficient_funds", "do_not_honor"] | None


@dataclass(frozen=True)
class PlannedAttempt:
    """One deterministic attempt within a scenario plan. Contains raw-event
    shape only -- no identifiers (the caller namespaces those per run), no
    scenario label, and no expected fraud decision."""

    attempt: int
    gap_seconds: int
    session_suffix: str
    card_suffix: str
    ip_suffix: str
    amount: float
    campaign_active: bool
    authorization_result: AuthorizationResult
    decline_reason: DeclineReason


def _legitimate_plan(
    *,
    gaps: tuple[int, ...],
    card_suffixes: tuple[str, ...],
    ip_suffixes: tuple[str, ...],
    amount: float,
    campaign_active: bool,
    decline_reasons: tuple[DeclineReason, ...],
) -> tuple[PlannedAttempt, ...]:
    """Shared builder for the four legitimate/borderline-legitimate
    scenarios: constant session, a small (possibly single) card/IP
    diversity, a constant amount (same cart/purchase every retry), and the
    final attempt always approved -- a real shopper stops retrying once
    payment succeeds."""
    total = len(gaps)
    return tuple(
        PlannedAttempt(
            attempt=i + 1,
            gap_seconds=gaps[i],
            session_suffix="session1",
            card_suffix=card_suffixes[i],
            ip_suffix=ip_suffixes[i],
            amount=amount,
            campaign_active=campaign_active,
            authorization_result="approved" if i == total - 1 else "declined",
            decline_reason=None if i == total - 1 else decline_reasons[i],
        )
        for i in range(total)
    )


def _normal_customer() -> tuple[PlannedAttempt, ...]:
    # One temporary processor hiccup, then success. Same device, card,
    # session and IP throughout -- no rotation of any kind.
    return _legitimate_plan(
        gaps=(0, 95),
        card_suffixes=("card1", "card1"),
        ip_suffixes=("ip1", "ip1"),
        amount=2400.0,
        campaign_active=False,
        decline_reasons=("generic_decline",),
    )


def _normal_bad_luck() -> tuple[PlannedAttempt, ...]:
    # Two genuine declines on the original card, then the shopper tries a
    # second card from a second network (e.g. switches from wifi to mobile
    # data) -- exactly one card switch and one IP switch, not mechanical
    # per-attempt rotation.
    return _legitimate_plan(
        gaps=(0, 55, 60, 50),
        card_suffixes=("card1", "card1", "card2", "card2"),
        ip_suffixes=("ip1", "ip1", "ip2", "ip2"),
        amount=1899.0,
        campaign_active=False,
        decline_reasons=("do_not_honor", "insufficient_funds", "generic_decline"),
    )


def _flash_standard() -> tuple[PlannedAttempt, ...]:
    # Flash-sale checkout: gateway is under load, the same card/session/IP
    # retries in quick succession until it clears.
    return _legitimate_plan(
        gaps=(0, 32, 30),
        card_suffixes=("card1", "card1", "card1"),
        ip_suffixes=("ip1", "ip1", "ip1"),
        amount=999.0,
        campaign_active=True,
        decline_reasons=("generic_decline", "generic_decline"),
    )


def _flash_hard_retry() -> tuple[PlannedAttempt, ...]:
    # Mostly the same card/session, hard-retried during a busy sale; only
    # on the last attempt does the shopper fall back to a second card.
    return _legitimate_plan(
        gaps=(0, 22, 20, 25, 28),
        card_suffixes=("card1", "card1", "card1", "card1", "card2"),
        ip_suffixes=("ip1", "ip1", "ip1", "ip1", "ip1"),
        amount=1499.0,
        campaign_active=True,
        decline_reasons=(
            "generic_decline",
            "generic_decline",
            "generic_decline",
            "generic_decline",
        ),
    )


def _burst_attacker() -> tuple[PlannedAttempt, ...]:
    # One device/session, a new card on almost every attempt, seconds-scale
    # gaps -- the shape that a card-testing burst actually looks like. The
    # processor declines every attempt; automated card testing essentially
    # never earns a genuine approval, independent of what our own policy
    # decides.
    amounts = (2.0, 3.0, 2.0, 5.0, 2.0, 4.0, 2.0, 3.0)
    gaps = (0, 4, 3, 4, 3, 4, 3, 4)
    return tuple(
        PlannedAttempt(
            attempt=i + 1,
            gap_seconds=gaps[i],
            session_suffix="session1",
            card_suffix=f"card{i + 1}",
            ip_suffix=f"ip{1 + i // 3}",
            amount=amounts[i],
            campaign_active=False,
            authorization_result="declined",
            decline_reason="do_not_honor",
        )
        for i in range(len(gaps))
    )


def _evasive_attacker() -> tuple[PlannedAttempt, ...]:
    # Rotates card/session/IP together, but only once every three attempts
    # (selective rotation) instead of every attempt. Gaps alternate short
    # bursts with longer cool-down pauses to look less mechanical than a
    # pure burst.
    gaps = (0, 40, 180, 45, 35, 190, 50, 40, 185)
    amounts = (5.0, 8.0, 4.0, 6.0, 9.0, 5.0, 7.0, 4.0, 6.0)
    return tuple(
        PlannedAttempt(
            attempt=i + 1,
            gap_seconds=gaps[i],
            session_suffix=f"session{1 + i // 3}",
            card_suffix=f"card{1 + i // 3}",
            ip_suffix=f"ip{1 + i // 3}",
            amount=amounts[i],
            campaign_active=False,
            authorization_result="declined",
            decline_reason="do_not_honor",
        )
        for i in range(len(gaps))
    )


def _patient_attacker() -> tuple[PlannedAttempt, ...]:
    # A new session on essentially every attempt (separate "visits" spread
    # over days), a slower card/IP cadence, and hours-scale gaps between
    # attempts -- patience over speed.
    gap_hours = (0, 6, 5, 7, 6, 8, 5, 9, 6)
    amounts = (3.0, 6.0, 4.0, 7.0, 3.0, 5.0, 4.0, 6.0, 3.0)
    return tuple(
        PlannedAttempt(
            attempt=i + 1,
            gap_seconds=gap_hours[i] * 3600,
            session_suffix=f"session{i + 1}",
            card_suffix=f"card{1 + i // 2}",
            ip_suffix=f"ip{1 + i // 2}",
            amount=amounts[i],
            campaign_active=False,
            authorization_result="declined",
            decline_reason="do_not_honor",
        )
        for i in range(len(gap_hours))
    )


SCENARIO_PLANS: dict[str, tuple[PlannedAttempt, ...]] = {
    "normal_customer": _normal_customer(),
    "normal_bad_luck": _normal_bad_luck(),
    "flash_standard": _flash_standard(),
    "flash_hard_retry": _flash_hard_retry(),
    "burst_attacker": _burst_attacker(),
    "evasive_attacker": _evasive_attacker(),
    "patient_attacker": _patient_attacker(),
}

#: Display metadata only -- deliberately contains no expected decision, no
#: scoring hint, and nothing that could leak into a precheck body.
SCENARIO_CATALOG: dict[str, dict] = {
    "normal_customer": {
        "label": "Everyday Checkout",
        "attempts": len(SCENARIO_PLANS["normal_customer"]),
    },
    "normal_bad_luck": {
        "label": "Bad-Luck Retry",
        "attempts": len(SCENARIO_PLANS["normal_bad_luck"]),
    },
    "flash_standard": {
        "label": "Flash Sale",
        "attempts": len(SCENARIO_PLANS["flash_standard"]),
    },
    "flash_hard_retry": {
        "label": "Flash-Sale Hard Retry",
        "attempts": len(SCENARIO_PLANS["flash_hard_retry"]),
    },
    "burst_attacker": {
        "label": "Burst Card Testing",
        "attempts": len(SCENARIO_PLANS["burst_attacker"]),
    },
    "evasive_attacker": {
        "label": "Evasive Card Testing",
        "attempts": len(SCENARIO_PLANS["evasive_attacker"]),
    },
    "patient_attacker": {
        "label": "Patient Card Testing",
        "attempts": len(SCENARIO_PLANS["patient_attacker"]),
    },
}
