"""Model v2: selection hygiene, artifact identity, and v1 preservation.

The claim these tests protect is that the candidate, its hyperparameters and
its calibration were all frozen from TRAIN cross-validation before the
validation split was read once.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest

from card_testing_sentinel.features.specification import (
    MODEL_FEATURES,
    MODEL_FEATURES_SHA256,
)
from card_testing_sentinel.features.specification_v2 import (
    MODEL_FEATURES_V2,
    MODEL_FEATURES_V2_SHA256,
)
from card_testing_sentinel.ml.candidates_v2 import (
    CandidateV2,
    add_interactions,
    candidate_grid_v2,
    interaction_name,
)
from card_testing_sentinel.ml.folds_v2 import (
    assert_fold_integrity,
    group_key,
    make_grouped_folds,
)

ROOT = Path(__file__).resolve().parents[2]
MODEL_DIR = ROOT / "artifacts/model_v2"
EVAL = ROOT / "artifacts/evaluation"
DATA = ROOT / "data/generated/development_v3"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def metadata() -> dict:
    return json.loads((MODEL_DIR / "metadata.json").read_text())


@pytest.fixture(scope="module")
def validation_report() -> dict:
    return json.loads((EVAL / "model_v2_validation_metrics.json").read_text())


@pytest.fixture(scope="module")
def features() -> pd.DataFrame:
    return pd.read_csv(DATA / "features_v2.csv")


# --- artifact identity ------------------------------------------------------


def test_the_artifact_binds_its_own_contract_and_data(metadata):
    assert metadata["feature_contract_sha256"] == MODEL_FEATURES_V2_SHA256
    assert metadata["model_sha256"] == sha256(MODEL_DIR / "risk_model_v2.joblib")
    assert metadata["training_config_sha256"] == sha256(
        ROOT / "configs/training_v2.yaml"
    )
    assert metadata["features_sha256"] == sha256(DATA / "features_v2.csv")
    assert metadata["feature_count"] == 39


def test_the_artifact_refuses_the_v1_contract(metadata):
    artifact = joblib.load(MODEL_DIR / "risk_model_v2.joblib")
    assert artifact.feature_contract_sha256 != MODEL_FEATURES_SHA256
    assert tuple(artifact.feature_names) == MODEL_FEATURES_V2
    with pytest.raises(KeyError):
        artifact.score_frame(pd.DataFrame([dict.fromkeys(MODEL_FEATURES, 0.0)]))


def test_model_v1_is_untouched():
    """v1 must stay loadable and identical while v2 is developed."""
    from card_testing_sentinel.modeling.model import READY, RiskModel

    v1 = json.loads((ROOT / "artifacts/model/metadata.json").read_text())
    assert v1["feature_contract_sha256"] == MODEL_FEATURES_SHA256
    assert RiskModel.load(ROOT, allow_degraded=False).status == READY
    assert (MODEL_DIR / "risk_model_v2.joblib").resolve() != (
        ROOT / "artifacts/model/risk_model.joblib"
    ).resolve()


def test_the_environment_and_seeds_are_recorded(metadata):
    assert metadata["training_seed"] == 90210443
    for key in ("python", "sklearn", "numpy", "pandas", "platform"):
        assert metadata["environment"][key]


# --- selection hygiene ------------------------------------------------------


def test_selection_and_calibration_never_saw_validation(metadata):
    assert metadata["validation_scored"] is False
    assert metadata["blind_evaluated"] is False
    assert metadata["training_rows"] > 0
    frame = pd.read_csv(DATA / "features_v2.csv", usecols=["split"])
    assert metadata["training_rows"] == int(frame.split.eq("train").sum())


def test_no_policy_was_selected_in_this_phase(validation_report):
    assert validation_report["policy_selected"] is False
    assert validation_report["blind_evaluated"] is False
    for name in ("operational_policy_v2.json", "policy_v2_candidates.csv"):
        assert not (ROOT / "artifacts/policy" / name).exists()


def test_blind_v1_1_remains_consumed_and_untouched():
    import scripts.freeze_blind_benchmark as freeze

    assert freeze.verify() == []
    manifest = json.loads((EVAL / "blind_freeze_manifest.json").read_text())
    assert manifest["consumed"] is True
    assert manifest["blind_version"] == "v1.1"


# --- grouped folds ----------------------------------------------------------


def test_folds_group_by_customer_not_device(features):
    devices = features.drop_duplicates("device_id")[
        ["device_id", "customer_id", "scenario"]
    ]
    folds = make_grouped_folds(devices, 5, 90210443)
    assert_fold_integrity(folds, 5)
    # a customer owning several devices lands entirely in one fold
    multi = folds.groupby("group_id").device_id.nunique()
    assert (multi > 1).any(), "no multi-device group to exercise"
    assert (folds.groupby("group_id").fold.nunique() == 1).all()


def test_group_key_falls_back_to_device_when_no_customer():
    frame = pd.DataFrame(
        {
            "device_id": ["d1", "d2"],
            "customer_id": ["c1", None],
            "scenario": ["s", "s"],
        }
    )
    assert list(group_key(frame)) == ["c1", "d2"]


def test_folds_are_deterministic(features):
    devices = features.drop_duplicates("device_id")[
        ["device_id", "customer_id", "scenario"]
    ]
    first = make_grouped_folds(devices, 5, 90210443)
    second = make_grouped_folds(devices.sample(frac=1.0, random_state=2), 5, 90210443)
    pd.testing.assert_frame_equal(
        first.sort_values("device_id").reset_index(drop=True),
        second.sort_values("device_id").reset_index(drop=True),
    )


# --- candidates -------------------------------------------------------------


def test_the_candidate_set_is_controlled():
    import yaml

    config = yaml.safe_load((ROOT / "configs/training_v2.yaml").read_text())
    families = {c.family for c in candidate_grid_v2(config)}
    assert families == {
        "logistic_regression",
        "logistic_interactions",
        "hist_gradient_boosting",
    }
    forbidden = {"random_forest", "xgboost", "lightgbm", "neural", "gnn"}
    assert not families & forbidden


def test_interactions_are_named_products_not_an_expansion():
    frame = pd.DataFrame({"a": [2.0, 3.0], "b": [5.0, 7.0], "c": [1.0, 1.0]})
    out = add_interactions(frame, (("a", "b"),))
    assert list(out[interaction_name("a", "b")]) == [10.0, 21.0]
    # only the named pair is added
    assert set(out.columns) - set(frame.columns) == {interaction_name("a", "b")}


def test_an_ablation_subset_drops_its_interactions_too():
    base = CandidateV2(
        identifier="x",
        family="logistic_interactions",
        parameters={"C": 1.0},
        features=("a", "b", "c"),
        interactions=(("a", "b"), ("b", "c")),
    )
    reduced = base.with_features(("a", "b"), "minus_c")
    assert reduced.interactions == (("a", "b"),)
    assert reduced.identifier == "x__minus_c"


# --- results are internally consistent --------------------------------------


def test_every_required_ablation_ran():
    ablations = pd.read_csv(EVAL / "model_v2_ablations.csv")
    expected = {
        "full_v2",
        "v1_equivalent_families",
        "minus_long_horizon",
        "minus_customer_context",
        "minus_card_history",
        "minus_correlated_duplicates",
    }
    assert set(ablations.feature_set) == expected
    full = ablations.loc[ablations.feature_set.eq("full_v2")].iloc[0]
    assert full.features == 39
    # every ablation is compared at the SAME flag rate, not a fixed threshold
    assert ablations.matched_flag_rate.nunique() == 1


def test_the_threshold_table_is_monotone(validation_report):
    table = pd.read_csv(EVAL / "model_v2_thresholds.csv")
    assert list(table.threshold) == [0.3, 0.4, 0.5, 0.6, 0.7, 0.8]
    assert table.attack_device_recall.is_monotonic_decreasing
    assert table.legitimate_device_fpr.is_monotonic_decreasing
    for column in ("attack_device_recall", "legitimate_device_fpr"):
        assert table[column].between(0, 1).all()


def test_the_model_beats_every_baseline_at_matched_friction():
    matched = pd.read_csv(EVAL / "model_v2_matched_fpr.csv")
    assert len(matched) >= 4
    assert (matched.recall_gain > 0).all(), matched.to_dict("records")


def test_no_metric_is_nan(validation_report):
    def walk(node):
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, float):
            assert np.isfinite(node)

    walk(validation_report)


def test_both_customer_segments_are_reported_and_neither_carries_the_model():
    segments = pd.read_csv(EVAL / "model_v2_segments.csv")
    assert set(segments.segment) == {"customer_absent", "customer_present"}
    # the model must not work only because signed-in users are easier
    absent = segments.loc[segments.segment.eq("customer_absent")].iloc[0]
    present = segments.loc[segments.segment.eq("customer_present")].iloc[0]
    assert abs(absent.pr_auc - present.pr_auc) < 0.10
    assert absent.pr_auc > 0.5 and present.pr_auc > 0.5


def test_customer_id_present_is_not_the_dominant_signal():
    """A large positive weight here would mean 'no account = attack'."""
    coefficients = pd.read_csv(EVAL / "model_v2_coefficients.csv").set_index("feature")
    presence = coefficients.loc["customer_id_present", "coefficient"]
    strongest = coefficients.absolute.max()
    assert presence < 0, "absent identity must not be encoded as risk-raising"
    assert abs(presence) < strongest
