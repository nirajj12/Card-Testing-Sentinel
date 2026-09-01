"""Hand-authored raw-event plans for the demo walkthroughs.

Each scenario is a fixed sequence of attempts. A plan contains only what a
merchant sees at request time (timing, session, IP, amount, campaign flag)
plus an honest guess at the *verified outcome* that would come back later
(approved/declined, and -- for the demo -- a synthetic card last4/network
that Razorpay would report post-hoc). No scenario encodes an expected
allow/review/block decision; that is discovered by running the plan through
the real service.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

AuthorizationResult = Literal["approved", "declined"]
FailureReason = Literal["generic_decline", "insufficient_funds", "do_not_honor"] | None


@dataclass(frozen=True)
class PlannedAttempt:
    attempt: int
    gap_seconds: int
    session_suffix: str
    ip_suffix: str
    amount: float
    campaign_active: bool
    authorization_result: AuthorizationResult
    failure_reason: FailureReason
    #: synthetic metadata that a VERIFIED Razorpay outcome would carry; used
    #: only on the outcome event, never on the request.
    outcome_card_last4: str
    outcome_card_network: str


def _legit_plan(
    *,
    gaps: tuple[int, ...],
    ip_suffixes: tuple[str, ...],
    amount: float,
    campaign_active: bool,
    failure_reasons: tuple[FailureReason, ...],
    last4s: tuple[str, ...],
) -> tuple[PlannedAttempt, ...]:
    total = len(gaps)
    return tuple(
        PlannedAttempt(
            attempt=i + 1,
            gap_seconds=gaps[i],
            session_suffix="session1",
            ip_suffix=ip_suffixes[i],
            amount=amount,
            campaign_active=campaign_active,
            authorization_result="approved" if i == total - 1 else "declined",
            failure_reason=None if i == total - 1 else failure_reasons[i],
            outcome_card_last4=last4s[i],
            outcome_card_network="visa",
        )
        for i in range(total)
    )


def _normal_customer() -> tuple[PlannedAttempt, ...]:
    return _legit_plan(
        gaps=(0, 95),
        ip_suffixes=("ip1", "ip1"),
        amount=2400.0,
        campaign_active=False,
        failure_reasons=("generic_decline",),
        last4s=("4242", "4242"),
    )


def _normal_bad_luck() -> tuple[PlannedAttempt, ...]:
    return _legit_plan(
        gaps=(0, 55, 60, 50),
        ip_suffixes=("ip1", "ip1", "ip2", "ip2"),
        amount=1899.0,
        campaign_active=False,
        failure_reasons=("do_not_honor", "insufficient_funds", "generic_decline"),
        last4s=("4242", "4242", "8210", "8210"),
    )


def _flash_standard() -> tuple[PlannedAttempt, ...]:
    return _legit_plan(
        gaps=(0, 32, 30),
        ip_suffixes=("ip1", "ip1", "ip1"),
        amount=999.0,
        campaign_active=True,
        failure_reasons=("generic_decline", "generic_decline"),
        last4s=("4242", "4242", "4242"),
    )


def _flash_hard_retry() -> tuple[PlannedAttempt, ...]:
    return _legit_plan(
        gaps=(0, 22, 20, 25, 28),
        ip_suffixes=("ip1", "ip1", "ip1", "ip1", "ip1"),
        amount=1499.0,
        campaign_active=True,
        failure_reasons=(
            "generic_decline",
            "generic_decline",
            "generic_decline",
            "generic_decline",
        ),
        last4s=("4242", "4242", "4242", "4242", "8777"),
    )


def _attacker_plan(
    *,
    gaps: tuple[int, ...],
    amounts: tuple[float, ...],
    sessions: tuple[str, ...],
    ips: tuple[str, ...],
    last4s: tuple[str, ...],
    networks: tuple[str, ...],
) -> tuple[PlannedAttempt, ...]:
    return tuple(
        PlannedAttempt(
            attempt=i + 1,
            gap_seconds=gaps[i],
            session_suffix=sessions[i],
            ip_suffix=ips[i],
            amount=amounts[i],
            campaign_active=False,
            authorization_result="declined",
            failure_reason="do_not_honor",
            outcome_card_last4=last4s[i],
            outcome_card_network=networks[i],
        )
        for i in range(len(gaps))
    )


def _burst_attacker() -> tuple[PlannedAttempt, ...]:
    # Seconds-scale attempts, small amounts, fresh session every couple of
    # attempts -- the behavioural shape a merchant can actually see.
    return _attacker_plan(
        gaps=(0, 4, 3, 4, 3, 4, 3, 4, 3, 4),
        amounts=(2.0, 3.0, 2.0, 5.0, 2.0, 4.0, 2.0, 3.0, 2.0, 4.0),
        sessions=tuple(f"session{1 + i // 2}" for i in range(10)),
        ips=tuple(f"ip{1 + i // 3}" for i in range(10)),
        last4s=tuple(f"10{i:02d}" for i in range(1, 11)),
        networks=("visa", "mastercard", "visa", "rupay", "amex") * 2,
    )


def _evasive_attacker() -> tuple[PlannedAttempt, ...]:
    return _attacker_plan(
        gaps=(0, 40, 180, 45, 35, 190, 50, 40, 185),
        amounts=(5.0, 8.0, 4.0, 6.0, 9.0, 5.0, 7.0, 4.0, 6.0),
        sessions=tuple(f"session{1 + i // 3}" for i in range(9)),
        ips=tuple(f"ip{1 + i // 3}" for i in range(9)),
        last4s=("2001", "2001", "2001", "2002", "2002", "2002", "2003", "2003", "2003"),
        networks=("visa",) * 3 + ("mastercard",) * 3 + ("visa",) * 3,
    )


def _patient_attacker() -> tuple[PlannedAttempt, ...]:
    return _attacker_plan(
        gaps=tuple(h * 3600 for h in (0, 6, 5, 7, 6, 8, 5, 9, 6)),
        amounts=(3.0, 6.0, 4.0, 7.0, 3.0, 5.0, 4.0, 6.0, 3.0),
        sessions=tuple(f"session{i + 1}" for i in range(9)),
        ips=tuple(f"ip{1 + i // 2}" for i in range(9)),
        last4s=("3001", "3001", "3002", "3002", "3003", "3003", "3004", "3004", "3005"),
        networks=("visa",) * 9,
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

SCENARIO_CATALOG: dict[str, dict] = {
    name: {"label": label, "attempts": len(SCENARIO_PLANS[name])}
    for name, label in (
        ("normal_customer", "Everyday Checkout"),
        ("normal_bad_luck", "Bad-Luck Retry"),
        ("flash_standard", "Flash Sale"),
        ("flash_hard_retry", "Flash-Sale Hard Retry"),
        ("burst_attacker", "Burst Card Testing"),
        ("evasive_attacker", "Evasive Card Testing"),
        ("patient_attacker", "Patient Card Testing"),
    )
}
