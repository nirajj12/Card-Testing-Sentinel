"""Feature Contract v2 on the frozen Dataset v3: replay, gates, isolation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from card_testing_sentinel.features.batch import read_raw_events
from card_testing_sentinel.features.batch_v2 import (
    build_feature_table_v2,
    replay_events_v2,
)
from card_testing_sentinel.features.engine_v2 import FeatureEngineV2
from card_testing_sentinel.features.specification import MODEL_FEATURES
from card_testing_sentinel.features.specification_v2 import (
    CUSTOMER_FEATURES,
    MODEL_FEATURES_V2,
    MODEL_FEATURES_V2_SHA256,
    NEW_IN_V2,
)
from card_testing_sentinel.ml.validation_features_v2 import validate_features_v2

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data/generated/development_v3"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def features() -> pd.DataFrame:
    return pd.read_csv(DATA / "features_v2.csv")


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads((DATA / "features_v2_manifest.json").read_text())


@pytest.fixture(scope="module")
def sample_raw() -> pd.DataFrame:
    """A slice small enough to replay repeatedly, whole devices only."""
    raw = read_raw_events(DATA / "raw_events.csv")
    train = raw.loc[raw.split.eq("train")].sort_values(
        ["timestamp", "event_sequence"], kind="mergesort"
    )
    devices = list(dict.fromkeys(train.device_id.dropna()))[:400]
    return train.loc[train.device_id.isin(devices)].copy()


# --- the regenerated artifact -----------------------------------------------


def test_the_matrix_was_built_from_the_frozen_dataset_v3(manifest):
    assert manifest["source_raw_events_sha256"] == sha256(DATA / "raw_events.csv")
    assert manifest["source_labels_sha256"] == sha256(DATA / "labels.csv")
    assert manifest["features_v2_sha256"] == sha256(DATA / "features_v2.csv")
    assert manifest["feature_contract_sha256"] == MODEL_FEATURES_V2_SHA256
    assert manifest["feature_count"] == 39
    assert manifest["model_trained"] is False


def test_the_v1_projection_is_untouched_beside_it():
    """Model v1 must stay scoreable while v2 is being developed."""
    v1 = pd.read_csv(DATA / "features.csv", nrows=5)
    present = [name for name in v1.columns if name in set(MODEL_FEATURES)]
    assert present == list(MODEL_FEATURES)
    assert "successful_checkouts" in v1.columns
    assert not set(NEW_IN_V2) & set(v1.columns)


def test_one_row_per_request_and_every_value_finite(features):
    raw = read_raw_events(DATA / "raw_events.csv")
    requests = int(raw.event_type.eq("authorization_request").sum())
    assert len(features) == requests
    assert [n for n in features.columns if n in set(MODEL_FEATURES_V2)] == list(
        MODEL_FEATURES_V2
    )
    assert features.loc[:, list(MODEL_FEATURES_V2)].notna().all().all()


# --- replay determinism -----------------------------------------------------


def test_replay_is_byte_identical_across_runs(sample_raw):
    first = replay_events_v2(sample_raw)
    second = replay_events_v2(sample_raw)
    pd.testing.assert_frame_equal(first, second)


def test_row_order_does_not_change_the_features(sample_raw):
    """Ordering metadata, not row order, defines the replay."""
    shuffled = sample_raw.sample(frac=1.0, random_state=11)
    pd.testing.assert_frame_equal(
        replay_events_v2(sample_raw),
        replay_events_v2(shuffled),
    )


def test_online_processing_matches_a_single_batch_rebuild(sample_raw):
    """State carried forward incrementally must equal one continuous replay.

    This is the v2-specific risk: customer state spans devices, so a
    partial-then-resume replay could diverge where v1's per-device state
    could not.
    """
    ordered = sample_raw.sort_values(["timestamp", "event_sequence"], kind="mergesort")
    split = len(ordered) // 2
    engine = FeatureEngineV2()
    first = replay_events_v2(ordered.iloc[:split], engine=engine)
    second = replay_events_v2(ordered.iloc[split:], engine=engine)
    incremental = pd.concat([first, second], ignore_index=True)
    whole = replay_events_v2(ordered)
    pd.testing.assert_frame_equal(incremental, whole)


def test_interleaved_multi_device_customers_replay_consistently(sample_raw):
    """A customer's devices interleave in the global stream; the result must
    not depend on which device happened to be seen first."""
    labels = pd.read_csv(DATA / "labels.csv")
    multi = (
        labels.drop_duplicates("device_id")
        .groupby("customer_id")
        .device_id.nunique()
        .pipe(lambda s: s[s > 1])
    )
    assert len(multi) > 0, "no multi-device customer to exercise"
    devices = set(labels.loc[labels.customer_id.isin(multi.index[:40]), "device_id"])
    raw = read_raw_events(DATA / "raw_events.csv")
    slice_ = raw.loc[raw.device_id.isin(devices)]
    assert slice_.device_id.nunique() > len(multi.index[:40])
    pd.testing.assert_frame_equal(
        replay_events_v2(slice_),
        replay_events_v2(slice_.sample(frac=1.0, random_state=3)),
    )


def test_rebuilding_the_whole_matrix_reproduces_the_frozen_hash(manifest):
    """Deterministic regeneration of the published artifact."""
    raw = read_raw_events(DATA / "raw_events.csv")
    labels = pd.read_csv(DATA / "labels.csv")
    rebuilt = build_feature_table_v2(raw, labels)
    published = pd.read_csv(DATA / "features_v2.csv")
    pd.testing.assert_frame_equal(
        rebuilt.reset_index(drop=True),
        published.reset_index(drop=True),
        check_dtype=False,
    )


# --- gates on the real matrix -----------------------------------------------


def test_every_leakage_gate_passes_on_the_v2_features(features):
    report = validate_features_v2(features)
    assert report.passed, report.failures
    assert report.summary["shuffled_label_roc_auc"] <= 0.60


def test_no_new_feature_is_a_shortcut(features):
    report = validate_features_v2(features)
    for row in report.summary["univariate_max_f1_new_features"]:
        assert row["max_f1"] <= 0.85, row


def test_guest_traffic_is_neutral_not_extreme(features):
    absent = features.loc[features.customer_id_present.eq(0.0)]
    present = features.loc[features.customer_id_present.eq(1.0)]
    assert len(absent) > 0 and len(present) > 0
    for name in CUSTOMER_FEATURES:
        assert (absent[name] == 0.0).all(), name
    # guest traffic must exist on both sides of the label
    assert absent.label.mean() < 0.95
    assert absent.label.mean() > 0.05


def test_long_horizon_features_fire_on_the_intended_families(features):
    by_scenario = features.groupby("scenario")
    # patient attacks accumulate a week of activity their 24h counters miss
    patient = by_scenario.get_group("patient_tester_weeks")
    assert patient.requests_7d.median() > patient.requests_24h.median()
    # sparse multiday spreads across the most calendar days of any family
    sparse = by_scenario.get_group("sparse_multiday_tester")
    assert sparse.active_day_count_7d.median() >= 3.0
    # a returning customer genuinely accumulates tenure
    returning = by_scenario.get_group("returning_customer_multi_episode")
    identified = returning.loc[returning.customer_id_present.eq(1.0)]
    assert identified.customer_age_seconds.median() > 86400


def test_cross_device_context_is_not_an_attack_only_feature(features):
    multi = features.loc[features.customer_distinct_devices_7d >= 2]
    populations = set(multi.population)
    assert populations == {"legitimate", "attack"}, populations
    legitimate_devices = multi.loc[multi.label.eq(0)].device_id.nunique()
    attack_devices = multi.loc[multi.label.eq(1)].device_id.nunique()
    assert legitimate_devices > 100
    # neither side may own the signal outright
    share = legitimate_devices / (legitimate_devices + attack_devices)
    assert 0.15 < share < 0.85
    assert "multi_device_customer" in set(multi.loc[multi.label.eq(0)].scenario)
    assert "cross_device_campaign" in set(multi.loc[multi.label.eq(1)].scenario)


def test_customer_failures_overlap_the_genuine_failure_population(features):
    failing = features.loc[features.customer_failures_7d >= 1]
    assert set(failing.population) == {"legitimate", "attack"}
    assert failing.loc[failing.label.eq(0)].device_id.nunique() > 50


def test_train_and_validation_features_share_no_device(features):
    train = set(features.loc[features.split.eq("train"), "device_id"])
    validation = set(features.loc[features.split.eq("validation"), "device_id"])
    assert not train & validation
