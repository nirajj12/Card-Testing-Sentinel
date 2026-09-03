from __future__ import annotations

import ast
import copy
import json
from pathlib import Path

import pytest
import yaml

from scripts.run_economic_scenarios import (
    EconomicInputError,
    break_even_prevalence,
    calculate,
    legitimate_review_only_rate,
    run,
)

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "configs/economic_scenarios.yaml"
SCRIPT_PATH = ROOT / "scripts/run_economic_scenarios.py"


@pytest.fixture
def config():
    return yaml.safe_load(CONFIG_PATH.read_text())


def test_review_only_rate_is_review_or_higher_minus_block(config):
    rates = config["evaluation_basis"]
    assert legitimate_review_only_rate(rates) == pytest.approx(0.2056)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        (
            "quiet_day",
            {
                "attack_profiles": 100.0,
                "legitimate_profiles": 99_900.0,
                "attack_surfaced": 96.4,
                "attack_missed": 3.6,
                "legitimate_review_only": 20_539.44,
                "legitimate_hard_block": 159.84,
                "protected_attack_value_inr": 192_800.0,
                "review_friction_cost_inr": 821_577.6,
                "false_block_cost_inr": 79_920.0,
                "net_illustrative_value_inr": -708_697.6,
            },
        ),
        (
            "active_attack_campaign",
            {
                "attack_profiles": 2_000.0,
                "legitimate_profiles": 98_000.0,
                "attack_surfaced": 1_928.0,
                "attack_missed": 72.0,
                "legitimate_review_only": 20_148.8,
                "legitimate_hard_block": 156.8,
                "protected_attack_value_inr": 3_856_000.0,
                "review_friction_cost_inr": 805_952.0,
                "false_block_cost_inr": 78_400.0,
                "net_illustrative_value_inr": 2_971_648.0,
            },
        ),
        (
            "high_value_merchant",
            {
                "attack_profiles": 500.0,
                "legitimate_profiles": 99_500.0,
                "attack_surfaced": 482.0,
                "attack_missed": 18.0,
                "legitimate_review_only": 20_457.2,
                "legitimate_hard_block": 159.2,
                "protected_attack_value_inr": 4_820_000.0,
                "review_friction_cost_inr": 2_045_720.0,
                "false_block_cost_inr": 238_800.0,
                "net_illustrative_value_inr": 2_535_480.0,
            },
        ),
    ],
)
def test_default_scenario_arithmetic(config, name, expected):
    actual = calculate(config)["scenarios"][name]
    for field, value in expected.items():
        assert actual[field] == pytest.approx(value)


def test_break_even_formula_is_analytically_and_numerically_zero(config):
    rates = config["evaluation_basis"]
    costs = config["scenarios"]["quiet_day"]["costs_inr"]
    friction = 0.2056 * 40 + 0.0016 * 500
    expected = friction / (0.964 * 2000 + friction)
    actual = break_even_prevalence(costs, rates)
    assert actual == pytest.approx(expected)

    at_break_even = copy.deepcopy(config)
    at_break_even["scenarios"]["quiet_day"]["attack_prevalence"] = actual
    result = calculate(at_break_even)["scenarios"]["quiet_day"]
    assert result["net_illustrative_value_inr"] == pytest.approx(0.0, abs=1e-9)
    assert result["break_even_position"] == "at_break_even"


def test_above_and_below_break_even_classification(config):
    results = calculate(config)["scenarios"]
    assert results["quiet_day"]["break_even_position"] == "below_break_even"
    assert (
        results["active_attack_campaign"]["break_even_position"]
        == "above_break_even"
    )
    assert (
        results["high_value_merchant"]["break_even_position"]
        == "above_break_even"
    )


def test_zero_attack_prevalence_has_only_legitimate_friction(config):
    changed = copy.deepcopy(config)
    changed["scenarios"] = {"zero_attack": changed["scenarios"]["quiet_day"]}
    changed["scenarios"]["zero_attack"]["attack_prevalence"] = 0
    result = calculate(changed)["scenarios"]["zero_attack"]
    assert result["attack_profiles"] == 0
    assert result["no_sentinel_attack_cost_inr"] == 0
    assert result["net_illustrative_value_inr"] < 0


def test_zero_friction_costs_have_zero_break_even(config):
    changed = copy.deepcopy(config)
    costs = changed["scenarios"]["quiet_day"]["costs_inr"]
    costs["legitimate_review"] = 0
    costs["legitimate_block"] = 0
    result = calculate(changed)["scenarios"]["quiet_day"]
    assert result["break_even_attack_prevalence"] == 0
    assert result["net_illustrative_value_inr"] == pytest.approx(192_800.0)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("total_profiles",), -1),
        (("attack_prevalence",), -0.1),
        (("costs_inr", "missed_attack"), -1),
        (("costs_inr", "legitimate_review"), -1),
        (("costs_inr", "legitimate_block"), -1),
    ],
)
def test_negative_values_are_rejected(config, path, value):
    changed = copy.deepcopy(config)
    target = changed["scenarios"]["quiet_day"]
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    with pytest.raises(EconomicInputError):
        calculate(changed)


@pytest.mark.parametrize("prevalence", [-0.0001, 1.0001])
def test_attack_prevalence_must_be_between_zero_and_one(config, prevalence):
    changed = copy.deepcopy(config)
    changed["scenarios"]["quiet_day"]["attack_prevalence"] = prevalence
    with pytest.raises(EconomicInputError):
        calculate(changed)


def test_output_is_deterministic(config):
    first = json.dumps(calculate(config), indent=2, sort_keys=True)
    second = json.dumps(calculate(copy.deepcopy(config)), indent=2, sort_keys=True)
    assert first == second


def test_written_output_is_byte_for_byte_deterministic(tmp_path):
    first_path = tmp_path / "first.json"
    second_path = tmp_path / "second.json"
    run(CONFIG_PATH, first_path)
    run(CONFIG_PATH, second_path)
    assert first_path.read_bytes() == second_path.read_bytes()


def test_script_has_no_runtime_or_model_scoring_imports():
    tree = ast.parse(SCRIPT_PATH.read_text())
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    forbidden_prefixes = (
        "card_testing_sentinel",
        "joblib",
        "numpy",
        "pandas",
        "sklearn",
    )
    assert not any(name.startswith(forbidden_prefixes) for name in imports)
