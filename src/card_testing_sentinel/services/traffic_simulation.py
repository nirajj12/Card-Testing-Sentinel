"""Deterministic mixed merchant-traffic scheduling for the live console.

This module is a *scheduler*, not a second scoring path. It reuses the
existing hand-authored ``SCENARIO_PLANS`` unchanged and answers exactly one
question: in what global order, and at what virtual offsets, should a set of
independent simulated devices present their authorization requests?

Three invariants make this safe to feed into the real
``FraudDetectionService``:

1. **One device per scenario instance.** Every simulated device gets its own
   identity namespace, so a legitimate shopper's causal history is never
   merged with an attacker's. Two instances of the same scenario are two
   different devices.

2. **Globally non-decreasing virtual time.** ``FraudDetectionService``
   compares every incoming event against ``repository.latest_order()`` --
   a global ``(timestamp, event_sequence)`` tuple across *all* devices, not a
   per-device cursor. Attempts are therefore merge-sorted by absolute virtual
   offset before emission, and the caller advances one shared monotonic event
   sequence. Nothing here bypasses or weakens ``_assert_not_late``.

3. **No ground truth in the schedule payload.** A ``ScheduledAttempt``
   carries the scenario key only so the *simulator* can later attribute a
   decision it has already received. It is never placed in a
   ``PrecheckRequest`` (which forbids extra fields anyway) and never reaches
   feature computation, the model or the policy.

Runs are **seeded, not fixed**. An earlier version built the same devices in
the same order every time, which meant every run produced an identical feed
and identical detections -- a scripted scenario wearing a console's clothes,
which is the exact thing this view exists to avoid. Each run now draws its
own seed: the device count, the scenario mix, the arrival order and the
stagger between arrivals all vary. Passing a seed back reproduces a run
exactly, so a run can still be replayed when someone wants to inspect one.

Randomness lives only in *which devices show up and when*. The behaviour
plans themselves stay the hand-authored deterministic sequences in
``scenario_generation`` -- nothing here perturbs what an attacker or a
shopper actually does.

The pool deliberately excludes ``patient_attacker``: its hours-scale gaps
span days of virtual time and would make a single-screen feed unreadable.
Patient card testing stays a dedicated Replay Lab scenario where its long
horizon can be shown honestly, day by day.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from random import Random

from card_testing_sentinel.services.scenario_generation import (
    SCENARIO_PLANS,
    PlannedAttempt,
)


@dataclass(frozen=True)
class TrafficDevice:
    """One simulated device: which plan it runs and when it first appears."""

    index: int
    scenario: str
    start_offset_seconds: int

    @property
    def key(self) -> str:
        """Simulator-local device label. Deliberately carries no scenario
        name -- an operator watching the feed sees ``dev-04``, not
        ``burst-attacker-1``."""
        return f"dev-{self.index:02d}"


@dataclass(frozen=True)
class ScheduledAttempt:
    """One authorization attempt, positioned on the shared virtual clock."""

    offset_seconds: int
    device: TrafficDevice
    attempt: int
    spec: PlannedAttempt


#: Total devices in a run. Small enough to read in one screen, large enough
#: that a couple of attackers are genuinely hidden among real customers.
DEVICE_COUNT_RANGE = (14, 20)

#: How many of those are running an attack plan. Never zero -- a run with
#: nothing to find teaches nothing -- and never more than a fifth, because a
#: merchant's real traffic is overwhelmingly legitimate and that is what
#: makes a false positive expensive.
ATTACKER_COUNT_RANGE = (1, 3)

#: Legitimate behaviour, weighted the way a merchant's traffic actually
#: skews: mostly uneventful checkouts, some campaign load, a few genuine
#: repeated declines.
LEGITIMATE_WEIGHTS: tuple[tuple[str, int], ...] = (
    ("normal_customer", 6),
    ("flash_standard", 3),
    ("normal_bad_luck", 2),
    ("flash_hard_retry", 1),
)

#: Attack plans eligible for the live feed (see the module docstring for why
#: patient card testing is not among them).
ATTACK_POOL: tuple[str, ...] = ("burst_attacker", "evasive_attacker")

#: Virtual seconds between successive device arrivals, jittered per device.
ARRIVAL_STRIDE_RANGE = (24, 54)


def new_seed() -> int:
    """A fresh, unpredictable seed for a run the operator did not specify."""
    return secrets.randbelow(2**31)


def build_devices(seed: int) -> tuple[TrafficDevice, ...]:
    """Draw a run's devices from `seed`.

    Same seed, same devices -- so a run can be reproduced exactly. Different
    seed, different device count, different mix, different arrival order, and
    therefore attackers sitting at different places in the feed.
    """
    rng = Random(seed)
    total = rng.randint(*DEVICE_COUNT_RANGE)
    attackers = min(rng.randint(*ATTACKER_COUNT_RANGE), max(1, total // 5))

    scenarios = [rng.choice(ATTACK_POOL) for _ in range(attackers)]
    names = [name for name, _weight in LEGITIMATE_WEIGHTS]
    weights = [weight for _name, weight in LEGITIMATE_WEIGHTS]
    scenarios.extend(rng.choices(names, weights=weights, k=total - attackers))
    rng.shuffle(scenarios)

    devices = []
    elapsed = 0
    for position, scenario in enumerate(scenarios):
        devices.append(
            TrafficDevice(
                index=position + 1,
                scenario=scenario,
                start_offset_seconds=elapsed,
            )
        )
        elapsed += rng.randint(*ARRIVAL_STRIDE_RANGE)
    return tuple(devices)


def build_schedule(
    devices: tuple[TrafficDevice, ...],
) -> tuple[ScheduledAttempt, ...]:
    """Merge every device's plan into one globally ordered attempt schedule.

    Each ``PlannedAttempt.gap_seconds`` is a delta *since that device's
    previous attempt*, so offsets accumulate per device and are then
    merge-sorted across devices. Ties are broken deterministically by
    (device index, attempt) so a given device set always yields the same
    schedule.
    """
    attempts: list[ScheduledAttempt] = []
    for device in devices:
        elapsed = device.start_offset_seconds
        for spec in SCENARIO_PLANS[device.scenario]:
            elapsed += spec.gap_seconds
            attempts.append(
                ScheduledAttempt(
                    offset_seconds=elapsed,
                    device=device,
                    attempt=spec.attempt,
                    spec=spec,
                )
            )
    attempts.sort(key=lambda row: (row.offset_seconds, row.device.index, row.attempt))
    return tuple(attempts)


def schedule_for(
    seed: int,
) -> tuple[tuple[TrafficDevice, ...], tuple[ScheduledAttempt, ...]]:
    devices = build_devices(seed)
    return devices, build_schedule(devices)
