"""Scenario definitions and latent behaviour draws.

A scenario says what an actor is *trying to do*. It never says what the
observable events must look like. It declares ranges for latent behaviour
parameters -- retry cadence, how often a payment instrument is actually
usable, how much identity churns -- and the generator draws one concrete
value per actor from those ranges.

The ranges overlap on purpose. `repeated_genuine_failures` (a shopper whose
card keeps declining) and `merchant_typical_amounts` (a tester using
ordinary amounts) both draw low `method_validity`; `network_retry_storm`
and `fast_burst` both draw seconds-scale gaps. A single feature therefore
cannot recover the label, which is the point of the whole exercise.

Nothing here reads the policy thresholds. "Evasive" means a broadly slower,
quieter cadence, not a value computed from the current rule constants.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

import numpy as np

Range = tuple[float, float]

#: Latent parameters a later phase may override (used by warm-up families).
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


@dataclass(frozen=True)
class ScenarioConfig:
    name: str
    population: str
    weight: float
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
    device_pool: tuple[int, int]
    customer_pool: tuple[int, int]
    ip_pool: str
    amount_style_weights: dict[str, float]
    phases: tuple[dict[str, Any], ...] = ()
    merchant_kinds: tuple[str, ...] | None = None
    #: Arrive while the chosen merchant is actually running a campaign.
    prefers_campaign: bool = False
    #: Blind-only: a long inactivity gap after the first attempt, so the
    #: device carries real age but no recent history. (0, 0) disables it.
    dormant_gap_days: tuple[float, float] = (0.0, 0.0)
    #: Blind-only: alternate short bursts with long quiet periods, instead of
    #: one cadence throughout. None disables it.
    burst_pause: dict[str, Any] | None = None

    @property
    def label(self) -> int:
        return int(self.population == "attack")


@dataclass(frozen=True)
class Behavior:
    """One actor's concrete latent parameters."""

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
    device_pool: int
    customer_pool: int
    ip_pool: str
    amount_style_weights: dict[str, float]
    #: (after_fraction, already-drawn overrides) applied part-way through a run
    phases: tuple[tuple[float, dict[str, Any]], ...] = ()

    def at(self, attempt_index: int) -> Behavior:
        """Behaviour in force at an attempt, applying any phase override.

        A warm-up actor behaves like an ordinary customer for the first part
        of its run and then shifts. That is a change of latent parameters,
        not a change of label.
        """
        progress = attempt_index / max(self.attempts, 1)
        current = self
        for after_fraction, overrides in self.phases:
            if progress >= after_fraction:
                current = replace(current, **overrides)
        return current


def load_scenarios(config: dict) -> dict[str, ScenarioConfig]:
    defaults = config["scenario_defaults"]
    scenarios: dict[str, ScenarioConfig] = {}
    for name in sorted(config["scenarios"]):
        spec = {**defaults, **config["scenarios"][name]}
        scenarios[name] = ScenarioConfig(
            name=name,
            population=str(spec["population"]),
            weight=float(spec["weight"]),
            attempts=(int(spec["attempts"][0]), int(spec["attempts"][1])),
            gap_seconds=(float(spec["gap_seconds"][0]), float(spec["gap_seconds"][1])),
            gap_spread=(float(spec["gap_spread"][0]), float(spec["gap_spread"][1])),
            method_validity=(
                float(spec["method_validity"][0]),
                float(spec["method_validity"][1]),
            ),
            network_instability=(
                float(spec["network_instability"][0]),
                float(spec["network_instability"][1]),
            ),
            session_rotation=(
                float(spec["session_rotation"][0]),
                float(spec["session_rotation"][1]),
            ),
            ip_rotation=(float(spec["ip_rotation"][0]), float(spec["ip_rotation"][1])),
            instrument_reuse=(
                float(spec["instrument_reuse"][0]),
                float(spec["instrument_reuse"][1]),
            ),
            checkout_completion=(
                float(spec["checkout_completion"][0]),
                float(spec["checkout_completion"][1]),
            ),
            continue_after_success=(
                float(spec["continue_after_success"][0]),
                float(spec["continue_after_success"][1]),
            ),
            device_pool=(int(spec["device_pool"][0]), int(spec["device_pool"][1])),
            customer_pool=(
                int(spec["customer_pool"][0]),
                int(spec["customer_pool"][1]),
            ),
            ip_pool=str(spec["ip_pool"]),
            amount_style_weights=dict(spec["amount_style_weights"]),
            phases=tuple(spec.get("phases") or ()),
            merchant_kinds=(
                tuple(spec["merchant_kinds"]) if spec.get("merchant_kinds") else None
            ),
            prefers_campaign=bool(spec.get("prefers_campaign", False)),
            dormant_gap_days=(
                float(spec.get("dormant_gap_days", (0.0, 0.0))[0]),
                float(spec.get("dormant_gap_days", (0.0, 0.0))[1]),
            ),
            burst_pause=spec.get("burst_pause") or None,
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


def draw_behavior(
    rng: np.random.Generator,
    scenario: ScenarioConfig,
    *,
    gap_multiplier: float = 1.0,
    attempts_bonus: int = 0,
) -> Behavior:
    """One actor's latent parameters, drawn uniformly inside the scenario's
    declared ranges. Two actors in the same scenario are not identical, and
    an actor near the edge of its range can look like an actor from a
    different population."""
    low, high = scenario.attempts
    return Behavior(
        attempts=int(rng.integers(low, high + 1)) + attempts_bonus,
        gap_seconds=float(rng.uniform(*scenario.gap_seconds)) * gap_multiplier,
        gap_spread=float(rng.uniform(*scenario.gap_spread)),
        method_validity=float(rng.uniform(*scenario.method_validity)),
        network_instability=float(rng.uniform(*scenario.network_instability)),
        session_rotation=float(rng.uniform(*scenario.session_rotation)),
        ip_rotation=float(rng.uniform(*scenario.ip_rotation)),
        instrument_reuse=float(rng.uniform(*scenario.instrument_reuse)),
        checkout_completion=float(rng.uniform(*scenario.checkout_completion)),
        continue_after_success=float(rng.uniform(*scenario.continue_after_success)),
        device_pool=int(
            rng.integers(scenario.device_pool[0], scenario.device_pool[1] + 1)
        ),
        customer_pool=int(
            rng.integers(scenario.customer_pool[0], scenario.customer_pool[1] + 1)
        ),
        ip_pool=scenario.ip_pool,
        amount_style_weights=dict(scenario.amount_style_weights),
        phases=tuple(
            _draw_phase(rng, phase, gap_multiplier) for phase in scenario.phases
        ),
    )
