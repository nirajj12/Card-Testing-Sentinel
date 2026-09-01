"""Generator -> FeatureEngine replay -> validation, end to end.

Features are produced only by replaying raw events through the *runtime*
engine, so this also proves the generated lifecycle is one the live service
accepts.
"""

from __future__ import annotations

import copy
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from card_testing_sentinel.features.batch import build_feature_table, replay_events
from card_testing_sentinel.features.specification import MODEL_FEATURES
from card_testing_sentinel.ml.generator import (
    generate_development_dataset,
    load_config,
)
from card_testing_sentinel.ml.validation import DatasetValidator, ValidationReport

pytestmark = pytest.mark.slow

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def config() -> dict:
    small = copy.deepcopy(load_config(ROOT / "configs/training.yaml"))
    small["splits"]["train"]["devices"] = 320
    small["splits"]["validation"]["devices"] = 150
    # a few-hundred-device sample cannot fill 22 scenarios past the
    # production floors; coverage itself is asserted in the generator tests
    small["gates"]["min_scenario_devices"] = 1
    small["gates"]["min_scenario_requests"] = 1
    return small


@pytest.fixture(scope="module")
def dataset(config) -> dict:
    bundle = generate_development_dataset(config)
    bundle["features"] = build_feature_table(bundle["raw_events"], bundle["labels"])
    return bundle


def test_generated_events_replay_through_the_runtime_feature_engine(dataset):
    features = dataset["features"]
    requests = dataset["raw_events"].event_type.eq("authorization_request").sum()
    assert len(features) == requests
    assert list(
        features.columns[: len(("request_id", "device_id", "session_id", "timestamp"))]
    ) == [
        "request_id",
        "device_id",
        "session_id",
        "timestamp",
    ]
    assert [name for name in features.columns if name in set(MODEL_FEATURES)] == list(
        MODEL_FEATURES
    )
    values = features.loc[:, list(MODEL_FEATURES)].to_numpy(dtype=float)
    assert np.isfinite(values).all()


def test_feature_replay_is_deterministic(dataset):
    partition = dataset["raw_events"].pipe(
        lambda frame: frame.loc[frame.split.eq("train")]
    )
    first = replay_events(partition)
    second = replay_events(partition)
    pd.testing.assert_frame_equal(first, second)


def test_the_engine_never_receives_a_label(dataset):
    """`replay_events` is handed raw events only; labels are joined after."""
    partition = dataset["raw_events"].pipe(
        lambda frame: frame.loc[frame.split.eq("train")]
    )
    replayed = replay_events(partition)
    for forbidden in ("label", "population", "scenario", "merchant_kind"):
        assert forbidden not in replayed.columns


def test_labels_join_cleanly_onto_every_feature_row(dataset):
    features = dataset["features"]
    assert features.label.notna().all()
    assert features.label.isin({0, 1}).all()
    assert features.split.isin({"train", "validation"}).all()


def test_the_full_validation_suite_passes_on_generated_data(dataset, config):
    report = DatasetValidator(config["gates"]).validate(
        dataset["raw_events"], dataset["labels"], dataset["features"]
    )
    assert report.passed, report.failures
    assert (
        report.summary["shuffled_label_roc_auc"]
        <= config["gates"]["max_shuffled_label_roc_auc"]
    )
    assert set(report.summary["overlap_coefficient"]) and all(
        value >= config["gates"]["min_overlap_coefficient"]
        for value in report.summary["overlap_coefficient"].values()
    )


def test_no_single_feature_comes_close_to_solving_the_task(dataset, config):
    report = ValidationReport()
    DatasetValidator(config["gates"]).check_univariate_leakage(
        dataset["features"], report
    )
    assert report.passed, report.failures
    best = max(row["max_f1"] for row in report.summary["univariate_max_f1"])
    assert best <= config["gates"]["max_univariate_f1"]


# --- the gates must actually fire on deliberately broken data ---------------


def test_a_leaked_feature_fails_the_univariate_gate(dataset, config):
    broken = dataset["features"].copy()
    # the shortcut this whole design exists to prevent: a feature that IS the label
    broken["current_amount"] = broken.label * 500.0 + 1.0
    report = ValidationReport()
    DatasetValidator(config["gates"]).check_univariate_leakage(broken, report)
    assert not report.passed
    assert any("current_amount" in message for message in report.failures)


def test_disjoint_populations_fail_the_overlap_gate(dataset, config):
    broken = dataset["features"].copy()
    broken["requests_5m"] = np.where(broken.label.eq(1), 40.0, 1.0)
    report = ValidationReport()
    DatasetValidator(config["gates"]).check_overlap(broken, report)
    assert not report.passed
    assert any("requests_5m" in message for message in report.failures)


def test_an_outcome_without_a_request_fails_lifecycle_validation(dataset, config):
    broken = dataset["raw_events"].copy()
    orphan = broken.loc[broken.event_type.eq("authorization_outcome")].head(1).copy()
    orphan["event_id"] = "evt_orphan"
    orphan["request_id"] = "req_does_not_exist"
    broken = pd.concat([broken, orphan], ignore_index=True)
    report = ValidationReport()
    DatasetValidator(config["gates"]).check_lifecycle(broken, report)
    assert not report.passed
    assert any("outcome without" in message for message in report.failures)


def test_card_metadata_on_a_request_fails_lifecycle_validation(dataset, config):
    broken = dataset["raw_events"].copy()
    index = broken.index[broken.event_type.eq("authorization_request")][0]
    broken.loc[index, "card_last4"] = "4242"
    report = ValidationReport()
    DatasetValidator(config["gates"]).check_lifecycle(broken, report)
    assert not report.passed
    assert any("card_last4" in message for message in report.failures)


def test_device_overlap_across_splits_fails_split_validation(dataset, config):
    broken = dataset["labels"].copy()
    train_device = broken.loc[broken.split.eq("train"), "device_id"].iloc[0]
    index = broken.index[broken.split.eq("validation")][0]
    broken.loc[index, "device_id"] = train_device
    report = ValidationReport()
    DatasetValidator(config["gates"]).check_splits(
        broken, dataset["raw_events"], report
    )
    assert not report.passed
    assert any("device overlap" in message for message in report.failures)


def test_a_shuffled_label_probe_stays_near_random(dataset, config):
    report = ValidationReport()
    DatasetValidator(config["gates"]).check_shuffled_labels(dataset["features"], report)
    assert report.passed, report.failures
    assert 0.35 <= report.summary["shuffled_label_roc_auc"] <= 0.65


# --- Phase 3B realism gates -------------------------------------------------


def test_temporal_separation_is_strict(dataset):
    """The LAST training event must precede the FIRST validation event -- a
    long-horizon training actor must not bleed across the boundary."""
    times = dataset["raw_events"].assign(
        ts=lambda frame: pd.to_datetime(frame.timestamp, format="ISO8601")
    )
    windows = times.groupby("split").ts.agg(["min", "max"])
    assert windows.loc["train", "max"] < windows.loc["validation", "min"]


def test_overlapping_windows_fail_temporal_validation(dataset, config):
    broken = dataset["raw_events"].copy()
    index = broken.index[broken.split.eq("validation")][0]
    train_first = broken.loc[broken.split.eq("train"), "timestamp"].min()
    broken.loc[index, "timestamp"] = train_first
    report = ValidationReport()
    DatasetValidator(config["gates"]).check_splits(dataset["labels"], broken, report)
    assert not report.passed
    assert any("temporal separation" in message for message in report.failures)


def test_legitimate_decline_rate_is_reported_and_inside_the_band(dataset, config):
    report = ValidationReport()
    DatasetValidator(config["gates"]).check_outcome_realism(
        dataset["raw_events"], dataset["labels"], report
    )
    assert report.passed, report.failures
    rates = report.summary["decline_rate"]
    band = config["gates"]["legitimate_decline_rate"]
    assert band["fail_below"] <= rates["legitimate"] <= band["fail_above"]
    # the realistic merchant-book figure is reported separately and is lower
    assert rates["legitimate_ordinary_customers"] < rates["legitimate"]
    assert rates["attack"] > rates["legitimate"]


def test_an_implausible_legitimate_decline_rate_fails(dataset, config):
    broken = dataset["raw_events"].copy()
    legit = set(dataset["labels"].loc[dataset["labels"].label.eq(0), "device_id"])
    mask = broken.event_type.eq("authorization_outcome") & broken.device_id.isin(legit)
    broken.loc[mask, "authorization_result"] = "declined"
    report = ValidationReport()
    DatasetValidator(config["gates"]).check_outcome_realism(
        broken, dataset["labels"], report
    )
    assert not report.passed
    assert any("legitimate decline rate" in message for message in report.failures)


def test_scenario_balance_reports_devices_requests_and_shares(dataset, config):
    report = ValidationReport()
    DatasetValidator(config["gates"]).check_scenario_balance(
        dataset["raw_events"], dataset["labels"], report
    )
    assert report.passed, report.failures
    profile = report.summary["scenario_profile"]
    assert set(profile) == set(dataset["labels"].scenario.unique())
    for row in profile.values():
        for column in (
            "devices",
            "requests",
            "events",
            "mean_attempts_per_device",
            "share_of_population_requests",
            "decline_rate",
        ):
            assert column in row
    for population in ("legitimate", "attack"):
        shares = [
            row["share_of_population_requests"]
            for row in profile.values()
            if row["population"] == population
        ]
        assert abs(sum(shares) - 1.0) < 0.02


def test_a_dominating_scenario_fails_the_concentration_gate(dataset, config):
    """No behaviour may quietly become the benchmark by out-attempting the
    rest of its population."""
    labels = dataset["labels"].copy()
    legit = labels.label.eq(0)
    labels.loc[legit, "scenario"] = "returning_customer"
    report = ValidationReport()
    DatasetValidator(config["gates"]).check_scenario_balance(
        dataset["raw_events"], labels, report
    )
    assert not report.passed
    assert any("dominating" in message for message in report.failures)


def test_campaign_flag_follows_the_merchant_clock_not_the_actor(dataset):
    """`campaign_active` is a property of merchant + time: within one
    merchant's campaign window every request is flagged, and attackers and
    shoppers see the same context."""
    raw = dataset["raw_events"]
    requests = raw.loc[raw.event_type.eq("authorization_request")].assign(
        ts=lambda frame: pd.to_datetime(frame.timestamp, format="ISO8601")
    )
    flagged = requests.campaign_active.astype(bool)
    assert 0.0 < flagged.mean() < 0.9, "campaigns must be neither absent nor constant"

    # A merchant's flagged requests must form contiguous time windows: no two
    # requests at the same merchant and instant may disagree.
    conflict = requests.groupby(["merchant_id", "ts"]).campaign_active.nunique()
    assert conflict.max() == 1

    # Both populations transact during campaigns.
    tagged = requests.merge(
        dataset["labels"][["device_id", "label"]].drop_duplicates("device_id"),
        on="device_id",
        how="left",
    )
    seen = tagged.loc[tagged.campaign_active.astype(bool)].label.unique()
    assert set(seen) == {0, 1}
