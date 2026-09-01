"""Dataset v3 scenario definitions and latent behaviour draws.

A scenario says what an actor is *trying to do*. It never says what the
observable events must look like: it declares ranges, and the generator draws
one concrete value per actor from them. The ranges overlap between
populations on purpose -- a patient tester and an unlucky returning shopper
can draw the same cadence, the same instrument validity and the same episode
structure.

New in v3, and the reason this cannot reuse ``ml/scenarios.py`` (which is
hashed inside the Blind v1.1 freeze bundle and must not change):

* ``episodes`` / ``episode_gap_days`` -- an actor makes several separated
  visits over days or weeks instead of one contiguous run.
* ``devices`` / ``device_mode`` -- how many devices the actor uses and whether
  it settles on one per visit (``sticky``) or spreads across them
  (``spread``).
* ``login_multiplier`` / ``guest`` -- how likely this actor is signed in.
* ``customers_on_device`` -- several people sharing one device.

Nothing here reads a model coefficient, a policy threshold or any evaluation
result. "Patient" means a slower cadence, not a value computed from the
current thresholds.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

import numpy as np

Range = tuple[float, float]

#: Latent parameters a later phase may override.
PHASE_OVERRIDABLE = (
    "gap_seconds",
    "gap_spread",
    "method_validity",
    "network_instability",
    "session_rotation",
    "ip_rotation",
    "instrument_reuse",
    "checkout_completion",
    "amount_style_weights",
)

IP_POOLS = ("private", "shared", "mobile")
DEVICE_MODES = ("sticky", "spread")


@dataclass(frozen=True)
class ScenarioV3:
    name: str
    population: str
    weight: float
    episodes: tuple[int, int]
    episode_gap_days: Range
    attempts: tuple[int, int]
    gap_seconds: Range
    gap_spread: Range
    method_validity: Range
    network_instability: Range
    session_rotation: Range
    ip_rotation: Range
    instrument_reuse: Range
    checkout_completion: Range
    continue_after_success: Range
    devices: tuple[int, int]
    device_mode: str
    customers_on_device: tuple[int, int]
    ip_pool: str
    login_multiplier: Range
    guest: bool
    amount_style_weights: dict[str, float]
    phases: tuple[dict[str, Any], ...] = ()
    merchant_kinds: tuple[str, ...] | None = None
    prefers_campaign: bool = False

    @property
    def label(self) -> int:
        return int(self.population == "attack")


@dataclass(frozen=True)
class BehaviorV3:
    """One actor's concrete latent parameters."""

    episodes: int
    episode_gap_days: float
    attempts: int
    gap_seconds: float
    gap_spread: float
    method_validity: float
    network_instability: float
    session_rotation: float
    ip_rotation: float
    instrument_reuse: float
    checkout_completion: float
    continue_after_success: float
    devices: int
    device_mode: str
    customers_on_device: int
    ip_pool: str
    login_rate: float
    amount_style_weights: dict[str, float]
    phases: tuple[tuple[float, dict[str, Any]], ...] = ()

    @property
    def total_attempts(self) -> int:
        return max(self.episodes * self.attempts, 1)

    def at(self, attempt_index: int) -> BehaviorV3:
        """Behaviour in force at a global attempt index.

        Progress runs across the WHOLE actor run, not one episode, so a
        `persistent_card_problem_customer` whose card dies part-way through
        keeps failing on every later visit -- and a `warm_up_then_test`
        attacker switches once, not once per episode.
        """
        progress = attempt_index / self.total_attempts
        current = self
        for after_fraction, overrides in self.phases:
            if progress >= after_fraction:
                current = replace(current, **overrides)
        return current


def _pair(values) -> tuple[float, float]:
    return (float(values[0]), float(values[1]))


def _int_pair(values) -> tuple[int, int]:
    return (int(values[0]), int(values[1]))


def load_scenarios_v3(config: dict) -> dict[str, ScenarioV3]:
    defaults = config["scenario_defaults"]
    scenarios: dict[str, ScenarioV3] = {}
    for name in sorted(config["scenarios"]):
        spec = {**defaults, **config["scenarios"][name]}
        ip_pool = str(spec["ip_pool"])
        if ip_pool not in IP_POOLS:
            raise ValueError(f"{name}: unknown ip_pool {ip_pool!r}")
        device_mode = str(spec["device_mode"])
        if device_mode not in DEVICE_MODES:
            raise ValueError(f"{name}: unknown device_mode {device_mode!r}")
        scenarios[name] = ScenarioV3(
            name=name,
            population=str(spec["population"]),
            weight=float(spec["weight"]),
            episodes=_int_pair(spec["episodes"]),
            episode_gap_days=_pair(spec["episode_gap_days"]),
            attempts=_int_pair(spec["attempts"]),
            gap_seconds=_pair(spec["gap_seconds"]),
            gap_spread=_pair(spec["gap_spread"]),
            method_validity=_pair(spec["method_validity"]),
            network_instability=_pair(spec["network_instability"]),
            session_rotation=_pair(spec["session_rotation"]),
            ip_rotation=_pair(spec["ip_rotation"]),
            instrument_reuse=_pair(spec["instrument_reuse"]),
            checkout_completion=_pair(spec["checkout_completion"]),
            continue_after_success=_pair(spec["continue_after_success"]),
            devices=_int_pair(spec["devices"]),
            device_mode=device_mode,
            customers_on_device=_int_pair(spec["customers_on_device"]),
            ip_pool=ip_pool,
            login_multiplier=_pair(spec["login_multiplier"]),
            guest=bool(spec["guest"]),
            amount_style_weights=dict(spec["amount_style_weights"]),
            phases=tuple(spec.get("phases") or ()),
            merchant_kinds=(
                tuple(spec["merchant_kinds"]) if spec.get("merchant_kinds") else None
            ),
            prefers_campaign=bool(spec.get("prefers_campaign", False)),
        )
    return scenarios


def _draw_phase(
    rng: np.random.Generator, phase: dict[str, Any], gap_multiplier: float
) -> tuple[float, dict[str, Any]]:
    overrides: dict[str, Any] = {}
    for key, value in phase.items():
        if key == "after_fraction" or key not in PHASE_OVERRIDABLE:
            continue
        if key == "amount_style_weights":
            overrides[key] = dict(value)
        else:
            drawn = float(rng.uniform(float(value[0]), float(value[1])))
            overrides[key] = drawn * gap_multiplier if key == "gap_seconds" else drawn
    return float(phase["after_fraction"]), overrides


def draw_behavior_v3(
    rng: np.random.Generator,
    scenario: ScenarioV3,
    *,
    gap_multiplier: float = 1.0,
    attempts_bonus: int = 0,
) -> BehaviorV3:
    """One actor's latent parameters, drawn uniformly inside declared ranges.

    Two actors in the same family are never identical, and an actor near the
    edge of its range can look like an actor from the other population.
    """
    return BehaviorV3(
        episodes=int(rng.integers(scenario.episodes[0], scenario.episodes[1] + 1)),
        episode_gap_days=float(rng.uniform(*scenario.episode_gap_days)),
        attempts=int(rng.integers(scenario.attempts[0], scenario.attempts[1] + 1))
        + attempts_bonus,
        gap_seconds=float(rng.uniform(*scenario.gap_seconds)) * gap_multiplier,
        gap_spread=float(rng.uniform(*scenario.gap_spread)),
        method_validity=float(rng.uniform(*scenario.method_validity)),
        network_instability=float(rng.uniform(*scenario.network_instability)),
        session_rotation=float(rng.uniform(*scenario.session_rotation)),
        ip_rotation=float(rng.uniform(*scenario.ip_rotation)),
        instrument_reuse=float(rng.uniform(*scenario.instrument_reuse)),
        checkout_completion=float(rng.uniform(*scenario.checkout_completion)),
        continue_after_success=float(rng.uniform(*scenario.continue_after_success)),
        devices=int(rng.integers(scenario.devices[0], scenario.devices[1] + 1)),
        device_mode=scenario.device_mode,
        customers_on_device=int(
            rng.integers(
                scenario.customers_on_device[0], scenario.customers_on_device[1] + 1
            )
        ),
        ip_pool=scenario.ip_pool,
        login_rate=(
            0.0 if scenario.guest else float(rng.uniform(*scenario.login_multiplier))
        ),
        amount_style_weights=dict(scenario.amount_style_weights),
        phases=tuple(
            _draw_phase(rng, phase, gap_multiplier) for phase in scenario.phases
        ),
    )
