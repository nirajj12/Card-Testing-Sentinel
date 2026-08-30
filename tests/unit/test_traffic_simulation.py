"""Seeded mixed merchant-traffic scheduling.

The properties that matter are in tension and both must hold: consecutive
runs must actually differ (otherwise the console is a scripted scenario in
disguise), while a given seed must reproduce a run exactly (otherwise a run
can never be inspected twice). Everything else here guards the invariants
that make a schedule safe to feed into the real service.
"""

from __future__ import annotations

import json

from card_testing_sentinel.services.scenario_generation import (
    SCENARIO_CATALOG,
    SCENARIO_PLANS,
)
from card_testing_sentinel.services.traffic_simulation import (
    ATTACK_POOL,
    ATTACKER_COUNT_RANGE,
    DEVICE_COUNT_RANGE,
    LEGITIMATE_WEIGHTS,
    build_devices,
    build_schedule,
    new_seed,
    schedule_for,
)

SEEDS = (1, 7, 42, 1234, 99999, 2**30)


def test_every_scenario_in_the_pools_exists():
    for scenario in ATTACK_POOL:
        assert scenario in SCENARIO_PLANS
    for scenario, weight in LEGITIMATE_WEIGHTS:
        assert scenario in SCENARIO_PLANS
        assert weight >= 1


def test_pools_exclude_the_long_horizon_patient_scenario():
    """Patient card testing spans days of virtual time. Merging it into a
    single-screen live feed would either stretch the run across a virtual
    week or require silently compressing its gaps, which would misrepresent
    the behaviour. It stays a dedicated Replay Lab scenario."""
    names = {scenario for scenario, _weight in LEGITIMATE_WEIGHTS} | set(ATTACK_POOL)
    assert "patient_attacker" not in names
    assert "patient_attacker" in SCENARIO_PLANS  # still available for replay


def test_the_same_seed_reproduces_a_run_exactly():
    """Without this a run can never be inspected a second time."""
    for seed in SEEDS:
        first_devices, first = schedule_for(seed)
        second_devices, second = schedule_for(seed)
        shape = lambda group: [  # noqa: E731
            (d.index, d.scenario, d.start_offset_seconds) for d in group
        ]
        assert shape(first_devices) == shape(second_devices)
        assert [(r.offset_seconds, r.device.key, r.attempt) for r in first] == [
            (r.offset_seconds, r.device.key, r.attempt) for r in second
        ]


def test_different_seeds_produce_genuinely_different_runs():
    """The regression this exists to prevent: a fixed schedule made every
    run identical, so the console showed the same feed and the same
    detections every time -- a scripted scenario wearing a console's
    clothes."""
    signatures = set()
    counts = set()
    attacker_positions = set()
    for seed in range(60):
        devices = build_devices(seed)
        signatures.add(tuple((d.scenario, d.start_offset_seconds) for d in devices))
        counts.add(len(devices))
        attacker_positions.add(
            tuple(d.index for d in devices if d.scenario in ATTACK_POOL)
        )
    assert len(signatures) == 60, "every seed must produce a distinct run"
    assert len(counts) > 1, "device count must vary between runs"
    assert len(attacker_positions) > 30, "attackers must not sit in fixed slots"


def test_new_seed_is_in_range_and_not_constant():
    seeds = {new_seed() for _ in range(40)}
    assert len(seeds) > 1
    assert all(0 <= seed < 2**31 for seed in seeds)


def test_device_and_attacker_counts_stay_inside_their_declared_bounds():
    for seed in range(40):
        devices = build_devices(seed)
        assert DEVICE_COUNT_RANGE[0] <= len(devices) <= DEVICE_COUNT_RANGE[1]
        attackers = [d for d in devices if d.scenario in ATTACK_POOL]
        assert ATTACKER_COUNT_RANGE[0] <= len(attackers) <= ATTACKER_COUNT_RANGE[1]


def test_every_run_contains_at_least_one_attacker():
    """A run with nothing to find demonstrates nothing."""
    for seed in range(40):
        devices = build_devices(seed)
        assert any(d.scenario in ATTACK_POOL for d in devices)


def test_traffic_is_always_majority_legitimate():
    """A merchant's real traffic is overwhelmingly legitimate, which is what
    makes a false positive expensive. A mix that was mostly attackers would
    flatter the detector."""
    for seed in range(40):
        devices = build_devices(seed)
        attackers = sum(1 for d in devices if d.scenario in ATTACK_POOL)
        assert attackers < len(devices) / 2


def test_every_device_is_its_own_scenario_instance():
    """Two devices running the same plan must still be two devices. Merging
    a legitimate shopper's history with an attacker's -- or with another
    shopper's -- would make every causal feature meaningless."""
    for seed in SEEDS:
        devices = build_devices(seed)
        keys = [device.key for device in devices]
        assert len(keys) == len(set(keys))


def test_offsets_are_globally_non_decreasing():
    """The repository's late-event check compares a *global*
    (timestamp, event_sequence) tuple, not a per-device cursor, so the
    merged schedule must never step backwards in virtual time."""
    for seed in SEEDS:
        _devices, schedule = schedule_for(seed)
        offsets = [row.offset_seconds for row in schedule]
        assert offsets == sorted(offsets)


def test_each_device_keeps_its_plan_in_attempt_order():
    for seed in SEEDS:
        _devices, schedule = schedule_for(seed)
        seen: dict[str, int] = {}
        for row in schedule:
            previous = seen.get(row.device.key, 0)
            assert row.attempt == previous + 1
            seen[row.device.key] = row.attempt


def test_schedule_covers_every_planned_attempt_exactly_once():
    for seed in SEEDS:
        devices, schedule = schedule_for(seed)
        expected = sum(len(SCENARIO_PLANS[device.scenario]) for device in devices)
        assert len(schedule) == expected


def test_devices_actually_interleave():
    """If devices never interleaved, the feed would just be one scenario
    played after another and the console would prove nothing about mixed
    traffic."""
    for seed in SEEDS:
        _devices, schedule = schedule_for(seed)
        keys = [row.device.key for row in schedule]
        switches = sum(1 for i in range(1, len(keys)) if keys[i] != keys[i - 1])
        assert switches > len(set(keys))


def test_device_labels_never_encode_the_scenario_or_its_label():
    """An operator watching the feed must see `dev-04`, never
    `burst-attacker-1`. The device key is rendered in the UI and used to
    build identifiers, so a scenario name here would leak the answer."""
    for seed in SEEDS:
        for device in build_devices(seed):
            encoded = json.dumps(device.key)
            assert device.scenario not in encoded
            assert SCENARIO_CATALOG[device.scenario]["label"] not in encoded
            for name in SCENARIO_PLANS:
                assert name not in encoded


def test_build_schedule_accepts_an_explicit_device_tuple():
    devices = build_devices(11)
    schedule = build_schedule(devices)
    assert len(schedule) == sum(len(SCENARIO_PLANS[d.scenario]) for d in devices)
