"""Phase 12 Blind v2 dataset-only, independence, and freeze contracts."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from card_testing_sentinel.features.batch import read_raw_events
from card_testing_sentinel.features.batch_v2 import build_feature_table_v2
from card_testing_sentinel.ml.blind_v2_generator import (
    generate_blind_v2_bundle,
    load_config,
)
from card_testing_sentinel.ml.blind_v2_validation import (
    FORBIDDEN_DEPENDENCIES,
    check_generator_independence,
    check_no_label_conditioned_actor_branches,
)
from card_testing_sentinel.ml.validation import OUTCOME_ONLY_FIELDS, ValidationReport

pytestmark = pytest.mark.slow

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data/generated/blind_v2"
REPORT = ROOT / "artifacts/evaluation/blind_v2_validation_report.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def config() -> dict:
    return load_config(ROOT / "configs/blind_v2.yaml")


@pytest.fixture(scope="module")
def raw() -> pd.DataFrame:
    return read_raw_events(DATA / "raw_events.csv")


@pytest.fixture(scope="module")
def labels() -> pd.DataFrame:
    return pd.read_csv(DATA / "labels.csv")


@pytest.fixture(scope="module")
def features() -> pd.DataFrame:
    return pd.read_csv(DATA / "features_v2.csv")


@pytest.fixture(scope="module")
def report() -> dict:
    return json.loads(REPORT.read_text())


def test_generation_and_feature_projection_are_byte_deterministic(config):
    small = copy.deepcopy(config)
    small["population"]["target_devices"] = 320
    small["population"]["minimum_actors_per_scenario"] = 1

    def generate():
        bundle = generate_blind_v2_bundle(
            small,
            ROOT / "configs/blind_v2.yaml",
            ROOT / "docs/blind_v2_spec.md",
            ROOT / "data/generated/development_v3/manifest.json",
        )
        events = bundle["raw_events"].copy()
        events["split"] = "blind_v2"
        projected = build_feature_table_v2(events, bundle["labels"])
        return bundle, projected

    first, first_features = generate()
    second, second_features = generate()
    pd.testing.assert_frame_equal(first["raw_events"], second["raw_events"])
    pd.testing.assert_frame_equal(first["labels"], second["labels"])
    pd.testing.assert_frame_equal(first_features, second_features)


def test_every_declared_family_and_merchant_kind_is_realized(config, labels):
    assert set(labels.scenario) == set(config["scenarios"])
    assert set(labels.merchant_kind) == set(config["merchants"]["kinds"])


def test_every_labelled_attack_device_transacts(raw, labels):
    active = set(raw.loc[raw.event_type.eq("authorization_request"), "device_id"])
    attacks = set(labels.loc[labels.label.eq(1), "device_id"])
    assert attacks <= active


def test_identities_do_not_overlap_dataset_v3_or_blind_v1(raw):
    references = (
        read_raw_events(ROOT / "data/generated/development_v3/raw_events.csv"),
        read_raw_events(ROOT / "data/generated/blind/raw_events.csv"),
    )
    for reference in references:
        for column in (
            "event_id",
            "request_id",
            "device_id",
            "customer_id",
            "session_id",
            "ip_fingerprint",
            "merchant_id",
        ):
            assert not (set(raw[column].dropna()) & set(reference[column].dropna()))


def test_blind_v2_is_strictly_later_than_dataset_v3(raw):
    development = read_raw_events(ROOT / "data/generated/development_v3/raw_events.csv")
    assert (
        pd.to_datetime(raw.timestamp, format="ISO8601").min()
        > pd.to_datetime(development.timestamp, format="ISO8601").max()
    )


def test_guest_and_logged_in_traffic_exists_in_both_populations(raw, labels):
    requests = raw.loc[raw.event_type.eq("authorization_request")].merge(
        labels[["device_id", "label"]].drop_duplicates(), on="device_id"
    )
    for label in (0, 1):
        group = requests.loc[requests.label.eq(label)]
        assert group.customer_id.isna().any()
        assert group.customer_id.notna().any()


def test_multi_device_patient_sparse_dunning_and_warmup_requirements(labels, report):
    actors = labels.groupby(["actor_id", "label"]).device_id.nunique()
    assert (actors.loc[actors.index.get_level_values("label") == 0] >= 2).any()
    assert (actors.loc[actors.index.get_level_values("label") == 1] >= 2).any()
    behavior = report["summary"]["behavioral_requirements"]
    assert behavior["patient_low_velocity_request_share"] >= 0.60
    assert behavior["patient_actor_attempts"]["min"] >= 3
    assert behavior["patient_actor_attempts"]["max"] <= 8
    assert behavior["sparse_active_days"]["min"] >= 2
    assert behavior["shared_ip_legitimate_requests"] > 0
    assert behavior["shared_ip_attack_requests"] > 0
    for scenario in (
        "subscription_dunning_v2",
        "warm_up_then_attack_v2",
        "cross_device_strong",
        "cross_device_partial",
        "cross_device_weak_guest",
    ):
        assert scenario in set(labels.scenario)


def test_requests_expose_no_future_or_evaluation_metadata(raw):
    requests = raw.loc[raw.event_type.eq("authorization_request")]
    for column in OUTCOME_ONLY_FIELDS:
        assert requests[column].isna().all(), column
    assert not {
        "label",
        "population",
        "scenario",
        "actor_id",
        "linkage_class",
    } & set(raw.columns)


def test_generator_has_no_model_policy_or_label_conditioned_actor_branch():
    validation = ValidationReport()
    entries = (
        "card_testing_sentinel.ml.blind_v2_generator",
        "card_testing_sentinel.ml.primitives",
        "card_testing_sentinel.ml.merchants",
    )
    check_generator_independence(ROOT, entries, validation)
    check_no_label_conditioned_actor_branches(
        ROOT / "src/card_testing_sentinel/ml/blind_v2_generator.py", validation
    )
    assert validation.passed, validation.failures
    reachable = set(validation.summary["generator_reachable_modules"])
    for forbidden in FORBIDDEN_DEPENDENCIES:
        assert not any(module.startswith(forbidden) for module in reachable)


def test_shortcut_gates_pass_without_model_or_policy_metrics(report):
    assert report["status"] == "passed"
    assert report["failures"] == []
    assert max(row["max_f1"] for row in report["summary"]["univariate_max_f1"]) <= 0.85
    assert report["summary"]["shuffled_label_roc_auc"] <= 0.60
    assert report["summary"]["contains_model_scores"] is False
    assert report["summary"]["contains_policy_decisions"] is False


def test_manifest_and_reproducibility_hashes_match_disk():
    manifest = json.loads((DATA / "manifest.json").read_text())
    reproducibility = json.loads((DATA / "reproducibility.json").read_text())
    assert manifest["evaluated"] is False
    assert manifest["consumed"] is False
    assert reproducibility["byte_identical"] is True
    for key, name in (
        ("raw_events_sha256", "raw_events.csv"),
        ("labels_sha256", "labels.csv"),
        ("features_v2_sha256", "features_v2.csv"),
    ):
        assert manifest[key] == sha256(DATA / name)


def test_blind_v2_freeze_and_all_preservation_hashes_verify():
    import scripts.freeze_blind_benchmark as blind_v1_freeze
    import scripts.freeze_blind_v2 as blind_v2_freeze

    assert blind_v1_freeze.verify() == []
    assert blind_v2_freeze.verify() == []
    freeze = json.loads(
        (ROOT / "artifacts/evaluation/blind_v2_freeze_manifest.json").read_text()
    )
    consumption = json.loads(
        (ROOT / "artifacts/evaluation/blind_v2_consumption.json").read_text()
    )
    assert freeze["evaluated"] is True
    assert freeze["consumed"] is True
    assert consumption["evaluated"] is True
    assert consumption["consumed"] is True
    assert consumption["post_blind_tuning"] is False
    assert "dataset" in freeze
