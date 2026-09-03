"""Calculate deterministic illustrative economics from frozen PBRSS-v1 rates."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "configs/economic_scenarios.yaml"
DEFAULT_OUTPUT = ROOT / "artifacts/economics/phase_4d_economic_scenarios.json"

EXPECTED_VERSION = "phase-4d-v1"
EXPECTED_EVALUATION = "pbrss-v1"
EXPECTED_UNIT = "device_profile"
EXPECTED_RATES = {
    "attack_review_or_higher_rate": 0.964,
    "attack_block_rate": 0.5912,
    "legitimate_review_or_higher_rate": 0.2072,
    "legitimate_block_rate": 0.0016,
}
DISCLAIMER = (
    "All monetary assumptions in this analysis are illustrative merchant-side "
    "scenario inputs. They are not measured Razorpay economics, production "
    "savings, or observed merchant losses."
)


class EconomicInputError(ValueError):
    """Raised when economic scenario inputs violate the analysis contract."""


def _number(value: Any, field: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise EconomicInputError(f"{field} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise EconomicInputError(f"{field} must be finite")
    if result < 0 or (positive and result == 0):
        qualifier = "positive" if positive else "non-negative"
        raise EconomicInputError(f"{field} must be {qualifier}")
    return result


def legitimate_review_only_rate(rates: dict[str, float]) -> float:
    """Return REVIEW-only, excluding genuine profiles already hard-blocked."""
    return (
        rates["legitimate_review_or_higher_rate"]
        - rates["legitimate_block_rate"]
    )


def break_even_prevalence(
    costs: dict[str, float], rates: dict[str, float]
) -> float:
    """Return the exact prevalence at which estimated net value is zero."""
    attack_protection = rates["attack_review_or_higher_rate"] * costs[
        "missed_attack"
    ]
    legitimate_friction = (
        legitimate_review_only_rate(rates) * costs["legitimate_review"]
        + rates["legitimate_block_rate"] * costs["legitimate_block"]
    )
    denominator = attack_protection + legitimate_friction
    if denominator == 0:
        return 0.0
    return legitimate_friction / denominator


def analyze_scenario(
    name: str,
    scenario: dict[str, Any],
    rates: dict[str, float],
) -> dict[str, Any]:
    """Calculate one device-profile expected-value scenario without rounding."""
    total_profiles = _number(
        scenario.get("total_profiles"), f"{name}.total_profiles", positive=True
    )
    prevalence = _number(
        scenario.get("attack_prevalence"), f"{name}.attack_prevalence"
    )
    if prevalence > 1:
        raise EconomicInputError(f"{name}.attack_prevalence must be between 0 and 1")

    raw_costs = scenario.get("costs_inr")
    if not isinstance(raw_costs, dict):
        raise EconomicInputError(f"{name}.costs_inr must be a mapping")
    costs = {
        field: _number(raw_costs.get(field), f"{name}.costs_inr.{field}")
        for field in ("missed_attack", "legitimate_review", "legitimate_block")
    }

    attack_profiles = total_profiles * prevalence
    legitimate_profiles = total_profiles - attack_profiles
    attack_surfaced = attack_profiles * rates["attack_review_or_higher_rate"]
    attack_missed = attack_profiles - attack_surfaced
    review_only = legitimate_profiles * legitimate_review_only_rate(rates)
    hard_block = legitimate_profiles * rates["legitimate_block_rate"]

    protected_value = attack_surfaced * costs["missed_attack"]
    no_sentinel_cost = attack_profiles * costs["missed_attack"]
    missed_attack_cost = attack_missed * costs["missed_attack"]
    review_friction_cost = review_only * costs["legitimate_review"]
    false_block_cost = hard_block * costs["legitimate_block"]
    sentinel_cost = missed_attack_cost + review_friction_cost + false_block_cost
    net_value = no_sentinel_cost - sentinel_cost
    break_even = break_even_prevalence(costs, rates)

    if math.isclose(prevalence, break_even, rel_tol=0.0, abs_tol=1e-12):
        position = "at_break_even"
    elif prevalence > break_even:
        position = "above_break_even"
    else:
        position = "below_break_even"

    return {
        "title": str(scenario.get("title", name)),
        "total_profiles": total_profiles,
        "attack_prevalence": prevalence,
        "costs_inr": costs,
        "attack_profiles": attack_profiles,
        "legitimate_profiles": legitimate_profiles,
        "attack_surfaced": attack_surfaced,
        "attack_missed": attack_missed,
        "legitimate_review_only": review_only,
        "legitimate_hard_block": hard_block,
        "protected_attack_value_inr": protected_value,
        "no_sentinel_attack_cost_inr": no_sentinel_cost,
        "sentinel_missed_attack_cost_inr": missed_attack_cost,
        "review_friction_cost_inr": review_friction_cost,
        "false_block_cost_inr": false_block_cost,
        "total_sentinel_cost_inr": sentinel_cost,
        "net_illustrative_value_inr": net_value,
        "break_even_attack_prevalence": break_even,
        "break_even_position": position,
    }


def validate_config(config: Any) -> tuple[dict[str, float], dict[str, Any]]:
    """Validate schema and pin the analysis to the authoritative frozen rates."""
    if not isinstance(config, dict):
        raise EconomicInputError("configuration must be a mapping")
    if config.get("version") != EXPECTED_VERSION:
        raise EconomicInputError(f"version must be {EXPECTED_VERSION}")

    basis = config.get("evaluation_basis")
    if not isinstance(basis, dict):
        raise EconomicInputError("evaluation_basis must be a mapping")
    if basis.get("evaluation") != EXPECTED_EVALUATION:
        raise EconomicInputError(f"evaluation must be {EXPECTED_EVALUATION}")
    if basis.get("unit") != EXPECTED_UNIT:
        raise EconomicInputError(f"unit must be {EXPECTED_UNIT}")

    rates: dict[str, float] = {}
    for field, expected in EXPECTED_RATES.items():
        value = _number(basis.get(field), f"evaluation_basis.{field}")
        if value != expected:
            raise EconomicInputError(f"{field} must remain frozen at {expected}")
        rates[field] = value

    scenarios = config.get("scenarios")
    if not isinstance(scenarios, dict) or not scenarios:
        raise EconomicInputError("scenarios must be a non-empty mapping")
    return rates, scenarios


def calculate(config: Any) -> dict[str, Any]:
    """Create the complete deterministic Phase 4D result document."""
    rates, scenarios = validate_config(config)
    review_only_rate = legitimate_review_only_rate(rates)
    results = {
        name: analyze_scenario(name, scenario, rates)
        for name, scenario in scenarios.items()
    }
    return {
        "version": EXPECTED_VERSION,
        "purpose": "illustrative_device_profile_expected_value_analysis",
        "disclaimer": DISCLAIMER,
        "evaluation_basis": {
            "evaluation": EXPECTED_EVALUATION,
            "unit": EXPECTED_UNIT,
            **rates,
            "legitimate_review_only_rate": review_only_rate,
            "synthetic_evaluation_basis": True,
            "pbrss_rescored": False,
        },
        "baseline": {
            "name": "no_sentinel",
            "assumption": "all modeled attack profiles proceed",
            "formula": "attack_profiles * missed_attack_cost",
        },
        "scenarios": results,
    }


def run(config_path: Path, output_path: Path) -> dict[str, Any]:
    """Read configuration, calculate results, and write stable JSON."""
    config = yaml.safe_load(config_path.read_text())
    result = calculate(config)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print(json.dumps(run(args.config, args.output), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
