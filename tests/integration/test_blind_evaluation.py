"""The blind evaluation used the frozen system, once, and spent the benchmark.

These tests guard the claim the whole benchmark rests on: that the numbers in
`blind_metrics_v1_1.json` came from the exact frozen model and the exact
frozen policy applied to the exact frozen data, with nothing fitted, nothing
recalibrated and no threshold chosen along the way.
"""

from __future__ import annotations

import ast
import hashlib
import json
import math
from pathlib import Path

import pandas as pd
import pytest

from card_testing_sentinel.ml.blind_evaluation import (
    MERCHANT_CATEGORY,
    POLICY_KEYS,
    frozen_policy,
    load_frozen_model,
    mark_evaluation_started,
    merchant_category,
)
from card_testing_sentinel.ml.blind_generator import BlindBenchmarkError

ROOT = Path(__file__).resolve().parents[2]
EVALUATION = ROOT / "artifacts/evaluation"
METRICS = EVALUATION / "blind_metrics_v1_1.json"
FREEZE = EVALUATION / "blind_freeze_manifest.json"

#: Every source file on the blind evaluation path.
EVALUATOR_SOURCES = (
    ROOT / "src/card_testing_sentinel/ml/blind_evaluation.py",
    ROOT / "pipelines/evaluate_blind.py",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def metrics() -> dict:
    return json.loads(METRICS.read_text())


@pytest.fixture(scope="module")
def freeze() -> dict:
    return json.loads(FREEZE.read_text())


# --- the evaluation used the frozen system ----------------------------------


def test_the_result_embeds_the_exact_frozen_model_hash(metrics, freeze):
    recorded = metrics["hashes"]["model_sha256"]
    assert recorded == freeze["development"]["model_sha256"]
    assert recorded == sha256(ROOT / "artifacts/model/risk_model.joblib")


def test_the_result_embeds_the_exact_frozen_policy_hash(metrics, freeze):
    recorded = metrics["hashes"]["policy_sha256"]
    assert recorded == freeze["development"]["policy_sha256"]
    assert recorded == sha256(ROOT / "artifacts/policy/operational_policy.json")


def test_the_result_embeds_the_exact_feature_contract(metrics):
    from card_testing_sentinel.features.specification import MODEL_FEATURES_SHA256

    assert metrics["hashes"]["feature_contract_sha256"] == sha256(
        ROOT / "artifacts/model/feature_contract.json"
    )
    assert metrics["hashes"]["feature_contract_code_sha256"] == MODEL_FEATURES_SHA256


def test_the_result_embeds_the_exact_blind_dataset_hashes(metrics, freeze):
    for key, name in (
        ("raw_events_sha256", "raw_events.csv"),
        ("labels_sha256", "labels.csv"),
        ("features_sha256", "features.csv"),
        ("manifest_sha256", "manifest.json"),
    ):
        assert metrics["hashes"][key] == freeze["dataset"][key]
        assert metrics["hashes"][key] == sha256(ROOT / "data/generated/blind" / name)


def test_the_applied_policy_matches_the_frozen_artifact(metrics):
    artifact = json.loads(
        (ROOT / "artifacts/policy/operational_policy.json").read_text()
    )
    applied = metrics["policy_applied"]
    for key in (
        "family",
        "review_threshold",
        "block_threshold",
        "block_evidence",
        "campaign_review_increment",
        "campaign_block_increment",
        "block_ttl_seconds",
    ):
        assert applied[key] == artifact[key], key
    # the policy object is built from the artifact, not from copied constants
    assert set(POLICY_KEYS) <= set(artifact)
    policy = frozen_policy(artifact)
    assert policy.review_threshold == 0.60
    assert policy.block_threshold == 0.78
    assert policy.block_evidence == 2


def test_a_model_whose_hash_does_not_match_is_refused(tmp_path):
    fake = tmp_path / "risk_model.joblib"
    fake.write_bytes(b"not the frozen model")
    with pytest.raises(BlindBenchmarkError, match="does not match the frozen"):
        load_frozen_model(fake, "0" * 64)


# --- nothing was fitted, recalibrated or selected ---------------------------


def _called_names(tree: ast.AST) -> set[str]:
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            function = node.func
            if isinstance(function, ast.Attribute):
                names.add(function.attr)
            elif isinstance(function, ast.Name):
                names.add(function.id)
    return names


@pytest.mark.parametrize("source", EVALUATOR_SOURCES, ids=lambda p: p.name)
def test_the_evaluator_never_fits_anything(source):
    called = _called_names(ast.parse(source.read_text()))
    for forbidden in ("fit", "partial_fit", "fit_transform", "fit_predict"):
        assert forbidden not in called, f"{source.name} calls {forbidden}()"


def _identifiers(tree: ast.AST) -> set[str]:
    """Names actually referenced in code -- not words in prose. A docstring
    saying 'nothing is recalibrated here' must not read as a violation."""
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.alias):
            names.add(node.name.rsplit(".", 1)[-1])
            if node.asname:
                names.add(node.asname)
    return names


@pytest.mark.parametrize("source", EVALUATOR_SOURCES, ids=lambda p: p.name)
def test_the_evaluator_never_builds_a_calibrator(source):
    names = _identifiers(ast.parse(source.read_text()))
    for forbidden in (
        "CalibratedClassifierCV",
        "IsotonicRegression",
        "LogisticRegression",
        "calibrate",
        "set_params",
    ):
        assert forbidden not in names, f"{source.name} references {forbidden}"


@pytest.mark.parametrize("source", EVALUATOR_SOURCES, ids=lambda p: p.name)
def test_the_evaluator_never_selects_a_threshold(source):
    """Selection functions exist in policy_search; none may be called here."""
    called = _called_names(ast.parse(source.read_text()))
    for forbidden in (
        "candidate_configs",
        "evaluate_candidates",
        "select",
        "constraint_failures",
        "rank_key",
        "threshold_sweep",
        "run_ablation",
    ):
        assert forbidden not in called, f"{source.name} calls {forbidden}()"


def test_the_result_declares_that_nothing_was_refitted(metrics):
    evaluation = metrics["evaluation"]
    assert evaluation["refit_performed"] is False
    assert evaluation["recalibration_performed"] is False
    assert evaluation["threshold_selection_performed"] is False
    assert evaluation["one_time"] is True


# --- the numbers reconcile ---------------------------------------------------


def test_scenario_totals_reconcile_with_the_aggregate(metrics):
    scenarios = pd.DataFrame(metrics["scenario_metrics"])
    policy = metrics["policy_metrics"]["blind"]
    attack = scenarios.loc[scenarios.population.eq("attack")]
    legitimate = scenarios.loc[scenarios.population.eq("legitimate")]

    assert int(attack.devices.sum()) == policy["attack_devices"]
    assert int(legitimate.devices.sum()) == policy["legitimate_devices"]
    assert (
        int(legitimate.reviewed_devices.sum()) == policy["legitimate_reviewed_devices"]
    )
    assert int(legitimate.blocked_devices.sum()) == policy["legitimate_blocked_devices"]
    assert (
        int(attack.devices.sum() - attack.reviewed_devices.sum())
        == policy["attack_never_detected"]
    )


def test_merchant_totals_reconcile_with_the_aggregate(metrics):
    merchants = pd.DataFrame(metrics["merchant_metrics"])
    policy = metrics["policy_metrics"]["blind"]
    assert int(merchants.attack_devices.sum()) == policy["attack_devices"]
    assert int(merchants.legitimate_devices.sum()) == policy["legitimate_devices"]

    categories = pd.DataFrame(metrics["merchant_category_metrics"])
    assert int(categories.attack_devices.sum()) == policy["attack_devices"]
    assert int(categories.legitimate_devices.sum()) == policy["legitimate_devices"]
    # every realized kind lands in exactly one category
    assert set(merchants.merchant_kind) == {
        kind for kinds in MERCHANT_CATEGORY.values() for kind in kinds
    }
    assert "unclassified" not in set(merchants.merchant_kind.map(merchant_category))


def test_travel_is_not_counted_as_a_seen_merchant_kind():
    """No travel merchant was ever realized in the frozen development data."""
    development = pd.read_csv(ROOT / "data/generated/development/labels.csv")
    assert "travel" not in set(development.merchant_kind)
    assert merchant_category("travel") == "B_declared_but_unrealized_in_development"
    assert "travel" not in MERCHANT_CATEGORY["A_seen_in_development"]


def test_campaign_split_covers_every_device(metrics):
    campaign = pd.DataFrame(metrics["campaign_metrics"])
    policy = metrics["policy_metrics"]["blind"]
    assert set(campaign.campaign_active) == {True, False}
    assert int(campaign.attack_devices.sum()) == policy["attack_devices"]
    assert int(campaign.legitimate_devices.sum()) == policy["legitimate_devices"]


def test_no_metric_is_nan_or_out_of_range(metrics):
    def walk(node, path=""):
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            for index, item in enumerate(node):
                walk(item, f"{path}[{index}]")
        elif isinstance(node, float):
            assert math.isfinite(node), f"non-finite metric at {path}"

    walk(metrics)
    for block in ("blind", "validation"):
        scores = metrics["model_metrics"][block]
        for name in ("pr_auc", "roc_auc", "ece"):
            assert 0.0 <= scores[name] <= 1.0, f"{block}.{name}"
    policy = metrics["policy_metrics"]["blind"]
    for name in (
        "attack_review_or_higher_recall",
        "attack_block_recall",
        "legitimate_review_or_higher_rate",
        "legitimate_block_rate",
    ):
        assert 0.0 <= policy[name] <= 1.0, name
    # a block is a strict subset of review-or-higher
    assert policy["attack_block_recall"] <= policy["attack_review_or_higher_recall"]
    assert policy["legitimate_block_rate"] <= policy["legitimate_review_or_higher_rate"]


def test_the_validation_comparison_uses_the_frozen_development_results(metrics):
    development = json.loads((EVALUATION / "development_metrics.json").read_text())
    validation_policy = json.loads(
        (EVALUATION / "policy_validation_metrics.json").read_text()
    )
    assert metrics["model_metrics"]["validation"]["pr_auc"] == round(
        development["model_scores"]["pr_auc"], 4
    )
    assert metrics["policy_metrics"]["validation"] == validation_policy["aggregate"]
    for key, value in metrics["model_metrics"]["delta"].items():
        expected = round(
            metrics["model_metrics"]["blind"][key]
            - round(development["model_scores"][key], 4),
            4,
        )
        assert abs(value - expected) < 1e-6, key


# --- the artifact and the consumption record --------------------------------


def test_the_result_artifact_contains_every_preregistered_section(metrics):
    for section in (
        "blind_version",
        "evaluation",
        "hashes",
        "policy_applied",
        "prevalence",
        "model_metrics",
        "calibration",
        "policy_metrics",
        "detection_delay",
        "scenario_metrics",
        "validation_scenario_metrics",
        "merchant_metrics",
        "merchant_category_metrics",
        "campaign_metrics",
        "evidence_gate",
        "baselines",
        "miss_analysis",
        "friction_analysis",
        "shift_characterisation",
    ):
        assert section in metrics, section
    assert metrics["blind_version"] == "v1.1"


def test_the_result_names_the_shift_honestly(metrics):
    """A modest marginal shift must not be described as a heavy one."""
    text = metrics["shift_characterisation"].lower()
    assert "modest" in text
    assert "not a heavy covariate shift" in text
    assert "temporally held-out" in text


def test_the_prevalence_caveat_travels_with_the_result(metrics):
    prevalence = metrics["prevalence"]
    assert prevalence["blind_attack_device_fraction"] == 0.2
    assert "PR-AUC is prevalence-dependent" in prevalence["note"]
    assert prevalence["blind_devices"] == 3000


def test_the_benchmark_is_marked_consumed(freeze):
    assert freeze["consumed"] is True
    assert freeze["blind_evaluated"] is True
    assert freeze["blind_metrics_sha256"] == sha256(METRICS)


def test_a_second_evaluation_is_refused():
    """The repository must not allow another untouched-benchmark run."""
    with pytest.raises(BlindBenchmarkError, match="already consumed"):
        mark_evaluation_started(FREEZE, "v1.1")


def test_the_v1_revision_history_survived_the_evaluation(freeze):
    history = freeze["revision_history"]
    v1 = next(entry for entry in history if entry["blind_version"] == "v1")
    assert v1["blind_evaluated"] is False
    assert v1["consumed"] is False
    assert "never evaluated and was never consumed" in v1["reason"]
