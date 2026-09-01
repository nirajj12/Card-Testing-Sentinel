"""Policy selection is validation-only, deterministic and constraint-first."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest

from card_testing_sentinel.common.config import load_config
from card_testing_sentinel.features.specification import MODEL_FEATURES
from card_testing_sentinel.ml.policy_search import (
    candidate_configs,
    constraint_failures,
    cost_table,
    device_view,
    evaluate_candidates,
    merchant_view,
    rank_key,
    replay,
    scenario_view,
    select,
    summarise,
)
from card_testing_sentinel.policy.engine import RiskPolicy

pytestmark = pytest.mark.slow

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data/generated/development"


@pytest.fixture(scope="module")
def config() -> dict:
    return load_config(ROOT / "configs/policy.yaml")


@pytest.fixture(scope="module")
def validation() -> pd.DataFrame:
    features = pd.read_csv(DATA / "features.csv")
    raw = pd.read_csv(DATA / "raw_events.csv", dtype={"card_last4": "string"})
    campaign = raw.loc[
        raw.event_type.eq("authorization_request"), ["request_id", "campaign_active"]
    ]
    merged = features.merge(campaign, on="request_id", how="left")
    merged["campaign_active"] = (
        merged.campaign_active.astype("boolean").fillna(False).astype(bool)
    )
    return merged.loc[merged.split.eq("validation")].reset_index(drop=True)


@pytest.fixture(scope="module")
def risk(validation) -> np.ndarray:
    artifact = joblib.load(ROOT / "artifacts/model/risk_model.joblib")
    return artifact.score_frame(validation.loc[:, list(MODEL_FEATURES)])


@pytest.fixture(scope="module")
def devices(validation, risk, config) -> pd.DataFrame:
    return device_view(replay(validation, risk, RiskPolicy(config["policy"])))


# --- the selection only ever sees validation --------------------------------


def test_selection_uses_the_validation_split_only(validation):
    assert set(validation.split) == {"validation"}
    assert len(validation) > 0


def test_the_policy_was_selected_without_any_blind_data():
    """The blind specification, config, generator and -- since Phase 7 -- the
    blind *dataset* now exist, all by design: the benchmark is built and
    integrity-checked before any model touches it. What must NOT exist is a
    blind *result*. The policy was selected on validation alone, and nothing
    has looked at a held-out number."""
    # The policy artifact was written before any blind data existed and still
    # declares that -- it must never be edited to absorb a blind result.
    policy = json.loads((ROOT / "artifacts/policy/operational_policy.json").read_text())
    assert policy["blind_evaluated"] is False
    assert policy["selected_on"] == "validation split only"
    for path in (
        ROOT / "artifacts/evaluation/blind_metrics_v1.json",
        ROOT / "artifacts/evaluation/blind_metrics.json",
    ):
        assert not path.exists(), f"{path} must not exist"

    # The generated benchmark must itself declare that nothing scored it.
    blind_manifest = ROOT / "data/generated/blind/manifest.json"
    if blind_manifest.is_file():
        manifest = json.loads(blind_manifest.read_text())
        assert manifest["blind_evaluated"] is False
        assert manifest["contains_model_metrics"] is False
        assert manifest["contains_policy_metrics"] is False

    # The benchmark has since been evaluated once, but that happened strictly
    # after selection: the freeze pinned the policy hash before blind data
    # existed, and it still matches.
    freeze = json.loads(
        (ROOT / "artifacts/evaluation/blind_freeze_manifest.json").read_text()
    )
    assert freeze["development"]["frozen_utc"] < freeze["evaluation_started_utc"]
    assert (
        freeze["development"]["policy_sha256"]
        == hashlib.sha256(
            (ROOT / "artifacts/policy/operational_policy.json").read_bytes()
        ).hexdigest()
    )


def test_every_artifact_still_declares_no_blind_evaluation():
    for path in (
        ROOT / "artifacts/policy/operational_policy.json",
        ROOT / "artifacts/model/metadata.json",
        ROOT / "artifacts/evaluation/policy_validation_metrics.json",
    ):
        assert json.loads(path.read_text())["blind_evaluated"] is False


# --- replay + determinism ---------------------------------------------------


def test_replay_is_deterministic(validation, risk, config):
    policy = RiskPolicy(config["policy"])
    first = replay(validation, risk, policy)
    second = replay(validation, risk, policy)
    pd.testing.assert_frame_equal(first, second)


def test_replay_covers_every_validation_attempt(validation, risk, config):
    replayed = replay(validation, risk, RiskPolicy(config["policy"]))
    assert len(replayed) == len(validation)
    assert set(replayed.action) <= {"allow", "review", "block"}


def test_attempt_numbering_is_per_device_and_in_time_order(validation, risk, config):
    replayed = replay(validation, risk, RiskPolicy(config["policy"]))
    for _device, group in replayed.groupby("device_id"):
        ordered = group.sort_values("timestamp")
        assert list(ordered.attempt) == list(range(1, len(ordered) + 1))


def test_candidate_evaluation_is_deterministic(validation, risk, config):
    grid = candidate_configs(
        {
            "review_thresholds": [0.6],
            "block_thresholds": [0.78],
            "block_evidence_counts": [2],
            "block_elevated_counts": [2],
            "persistent_block_evidence_counts": [1],
            "campaign_increments": [[0.0, 0.0]],
        },
        {
            "block_ttl_seconds": 3600,
            "persistence_window_hours": 24,
            "history_cap": 16,
            "degraded_review_rule_score": 4,
            "degraded_block_rule_score": 6,
        },
    )
    first, _ = evaluate_candidates(validation, risk, grid, config["policy_constraints"])
    second, _ = evaluate_candidates(
        validation, risk, grid, config["policy_constraints"]
    )
    pd.testing.assert_frame_equal(first, second)


# --- constraints do real work -----------------------------------------------


def test_the_selected_policy_satisfies_every_declared_constraint(devices, config):
    summary = summarise(devices)
    failures = constraint_failures(
        summary, scenario_view(devices), config["policy_constraints"]
    )
    assert failures == []


def test_block_false_positives_are_materially_rarer_than_reviews(devices, config):
    summary = summarise(devices)
    ratio = config["policy_constraints"]["min_review_to_block_ratio"]
    assert (
        summary["legitimate_block_rate"] * ratio
        <= summary["legitimate_review_or_higher_rate"]
    )


def test_a_reckless_policy_is_rejected_by_the_constraints(validation, risk, config):
    """The budget must actually exclude something -- otherwise it is decoration."""
    reckless = RiskPolicy(
        {
            **config["policy"],
            "review_threshold": 0.1,
            "block_threshold": 0.2,
            "block_evidence": 0,
            "family": "threshold",
        }
    )
    reckless_devices = device_view(replay(validation, risk, reckless))
    failures = constraint_failures(
        summarise(reckless_devices),
        scenario_view(reckless_devices),
        config["policy_constraints"],
    )
    assert failures, "a 0.2 block threshold must break the friction budget"


def test_select_refuses_when_nothing_is_eligible():
    empty = pd.DataFrame({"eligible": [False], "candidate": ["x"]})
    with pytest.raises(RuntimeError, match="no policy candidate"):
        select(empty)


def test_hard_scenario_caps_are_enforced_per_scenario(devices, config):
    scenarios = scenario_view(devices)
    for scenario, cap in config["policy_constraints"][
        "max_scenario_block_rate"
    ].items():
        if scenario in scenarios.index:
            assert float(scenarios.loc[scenario, "block_rate"]) <= float(cap), scenario


def test_ranking_prefers_recall_then_blocks_then_speed():
    high = pd.Series(
        {
            "attack_review_or_higher_recall": 0.9,
            "attack_block_recall": 0.5,
            "median_first_review_attempt": 4.0,
            "legitimate_review_or_higher_rate": 0.05,
            "family": "threshold",
            "block_evidence": 0,
        }
    )
    low = pd.Series(
        {
            "attack_review_or_higher_recall": 0.8,
            "attack_block_recall": 0.9,
            "median_first_review_attempt": 2.0,
            "legitimate_review_or_higher_rate": 0.01,
            "family": "threshold",
            "block_evidence": 0,
        }
    )
    assert rank_key(high) < rank_key(low)


# --- reporting completeness -------------------------------------------------


def test_every_scenario_and_merchant_is_reported(devices, validation):
    scenarios = scenario_view(devices)
    assert set(scenarios.index) == set(validation.scenario.unique())
    merchants = merchant_view(devices)
    assert set(merchants.merchant_kind) == set(validation.merchant_kind.unique())


def test_detection_delay_is_reported_for_both_bands(devices):
    summary = summarise(devices)
    assert summary["median_first_review_attempt"] is not None
    assert summary["median_first_block_attempt"] is not None
    # a block needs more evidence, so it cannot arrive before a review
    assert (
        summary["median_first_block_attempt"] >= summary["median_first_review_attempt"]
    )


def test_the_cost_table_is_labelled_illustrative(devices, config):
    table = cost_table(devices, config["policy_costs"])
    assert "not Razorpay economics" in table["units"]
    assert sum(table["counts"].values()) == len(devices)


def test_saved_candidate_table_covers_every_family():
    table = pd.read_csv(ROOT / "artifacts/evaluation/policy_candidates.csv")
    assert set(table.family) == {"threshold", "evidence_gated", "persistent"}
    assert table.eligible.any() and not table.eligible.all()
