from __future__ import annotations

import copy
import json
from pathlib import Path

import pandas as pd
import pytest
import yaml

from card_testing_sentinel.features.batch_v3 import build_feature_table_v3
from card_testing_sentinel.features.specification_v3 import MODEL_FEATURES_V3
from card_testing_sentinel.ml.pbrss_v1_generator import (
    PBRSSV1Generator,
    build_manifest,
)

ROOT = Path(__file__).resolve().parents[2]


def fixture_config(devices: int = 160) -> dict:
    config = yaml.safe_load((ROOT / "configs/post_blind_stress_v1.yaml").read_text())
    config["population"]["devices"] = devices
    config["population"]["target_requests"] = devices * 4
    quotas = {
        "stealth_low_amount_drip": 8,
        "hybrid_credential_stuffing_probe": 8,
        "charity_micro_donation_spike": 16,
        "b2b_multi_corporate_card": 8,
        "mixed_card_probe": 24,
        "ordinary_checkout": 96,
    }
    for section in ("held_out", "background"):
        for name, spec in config["scenarios"][section].items():
            spec["device_target"] = quotas[name]
    config["population"]["cgnat_devices_per_subnet"] = 8
    return config


@pytest.fixture(scope="module")
def canonical_config() -> dict:
    return yaml.safe_load((ROOT / "configs/post_blind_stress_v1.yaml").read_text())


@pytest.fixture(scope="module")
def canonical_bundle(canonical_config: dict) -> dict:
    return PBRSSV1Generator(canonical_config).generate()


def csv_bytes(frame: pd.DataFrame) -> bytes:
    return frame.to_csv(index=False, lineterminator="\n").encode()


def test_small_generation_is_byte_deterministic(tmp_path: Path) -> None:
    config = fixture_config()
    first = PBRSSV1Generator(config).generate()
    second = PBRSSV1Generator(copy.deepcopy(config)).generate()
    for name in ("raw_events", "labels"):
        assert csv_bytes(first[name]) == csv_bytes(second[name])
        (tmp_path / f"{name}.csv").write_bytes(csv_bytes(first[name]))
    first_manifest = json.dumps(build_manifest(config, first), sort_keys=True).encode()
    second_manifest = json.dumps(
        build_manifest(config, second), sort_keys=True
    ).encode()
    assert first_manifest == second_manifest
    assert b"created_at" not in first_manifest
    assert b"timestamp" not in first_manifest


def test_different_seed_changes_output() -> None:
    config = fixture_config()
    other = copy.deepcopy(config)
    other["seed"] += 1
    assert csv_bytes(PBRSSV1Generator(config).generate()["raw_events"]) != csv_bytes(
        PBRSSV1Generator(other).generate()["raw_events"]
    )


def test_merchants_are_new_and_both_populations_cover_each_archetype() -> None:
    labels = PBRSSV1Generator(fixture_config()).generate()["labels"]
    development = pd.read_csv(
        ROOT / "data/generated/development_v4_1/labels.csv",
        usecols=["merchant_id"],
    )
    assert set(labels.merchant_id).isdisjoint(set(development.merchant_id))
    coverage = labels.groupby(["merchant_id", "merchant_kind"]).label.nunique()
    assert coverage.eq(2).all()
    assert {"b2b_wholesale", "donation_charity"}.issubset(labels.merchant_kind)


def test_held_out_scenarios_and_group_coherence() -> None:
    bundle = PBRSSV1Generator(fixture_config()).generate()
    labels = bundle["labels"]
    assert {
        "stealth_low_amount_drip",
        "hybrid_credential_stuffing_probe",
        "charity_micro_donation_spike",
        "b2b_multi_corporate_card",
    }.issubset(set(labels.scenario))
    assert labels.groupby("device_id").actor_id.nunique().eq(1).all()
    assert labels.groupby("actor_id").leakage_group_id.nunique().eq(1).all()
    raw = bundle["raw_events"]
    assert raw.event_sequence.is_monotonic_increasing
    assert raw.event_id.is_unique


def test_canonical_population_quotas_and_request_invariant(
    canonical_config: dict, canonical_bundle: dict
) -> None:
    labels = canonical_bundle["labels"]
    raw = canonical_bundle["raw_events"]
    assert labels.device_id.nunique() == 5000
    assert labels.loc[labels.label.eq(1), "device_id"].nunique() == 1250
    assert labels.loc[labels.label.eq(0), "device_id"].nunique() == 3750
    assert labels.merchant_id.nunique() == 16
    counts = labels.groupby("scenario").device_id.nunique().to_dict()
    assert counts == {
        "b2b_multi_corporate_card": 250,
        "charity_micro_donation_spike": 500,
        "hybrid_credential_stuffing_probe": 250,
        "mixed_card_probe": 750,
        "ordinary_checkout": 3000,
        "stealth_low_amount_drip": 250,
    }
    requests = raw.event_type.eq("authorization_request").sum()
    target = canonical_config["population"]["target_requests"]
    tolerance = canonical_config["population"]["request_target_tolerance_fraction"]
    assert target * (1 - tolerance) <= requests <= target * (1 + tolerance)


def test_scenario_semantics_use_declared_config(
    canonical_config: dict, canonical_bundle: dict
) -> None:
    raw = canonical_bundle["raw_events"]
    labels = canonical_bundle["labels"]
    request_rows = raw.loc[raw.event_type.eq("authorization_request")].merge(
        labels[["device_id", "scenario"]], on="device_id", validate="many_to_one"
    )
    stealth_spec = canonical_config["scenarios"]["held_out"]["stealth_low_amount_drip"]
    stealth = request_rows.loc[request_rows.scenario.eq("stealth_low_amount_drip")]
    assert stealth.amount.between(*stealth_spec["amount"]).all()
    attempts = stealth.groupby("device_id").size()
    assert attempts.between(*stealth_spec["attempts"]).all()
    timestamps = pd.to_datetime(stealth.timestamp, format="ISO8601")
    gaps = (
        timestamps.groupby(stealth.device_id).diff().dropna().dt.total_seconds() / 3600
    )
    assert gaps.between(*stealth_spec["gap_hours"]).all()
    spans = timestamps.groupby(stealth.device_id).agg(
        lambda values: values.max() - values.min()
    )
    assert spans.max() <= pd.Timedelta(days=stealth_spec["duration_days"])

    charity = request_rows.loc[request_rows.scenario.eq("charity_micro_donation_spike")]
    charity_spec = canonical_config["scenarios"]["held_out"][
        "charity_micro_donation_spike"
    ]
    charity_times = pd.to_datetime(charity.timestamp, format="ISO8601")
    assert charity.amount.between(*charity_spec["amount"]).all()
    assert charity_times.max() - charity_times.min() <= pd.Timedelta(
        hours=charity_spec["burst_hours"]
    )


def test_changed_fixture_declaration_changes_scenario_output() -> None:
    config = fixture_config()
    stealth = config["scenarios"]["held_out"]["stealth_low_amount_drip"]
    stealth["amount"] = [3.25, 3.25]
    stealth["attempts"] = [8, 8]
    config["population"]["target_requests"] += stealth["device_target"]
    bundle = PBRSSV1Generator(config).generate()
    rows = (
        bundle["raw_events"]
        .loc[bundle["raw_events"].event_type.eq("authorization_request")]
        .merge(
            bundle["labels"][["device_id", "scenario"]],
            on="device_id",
            validate="many_to_one",
        )
    )
    rows = rows.loc[rows.scenario.eq("stealth_low_amount_drip")]
    assert rows.amount.eq(3.25).all()
    assert rows.groupby("device_id").size().eq(8).all()


def test_b2b_card_rotation_and_outcome_regimes_overlap(canonical_bundle: dict) -> None:
    raw = canonical_bundle["raw_events"]
    labels = canonical_bundle["labels"]
    outcomes = raw.loc[raw.event_type.eq("authorization_outcome")].merge(
        labels[["device_id", "label", "scenario"]],
        on="device_id",
        validate="many_to_one",
    )
    b2b = outcomes.loc[outcomes.scenario.eq("b2b_multi_corporate_card")]
    assert b2b.groupby("device_id").card_last4.nunique().eq(4).all()
    b2b_success = b2b.authorization_result.eq("approved").groupby(b2b.device_id).mean()
    assert b2b_success.between(0.01, 0.99).all()

    outcome_rate = (
        outcomes.authorization_result.eq("approved")
        .groupby([outcomes.device_id, outcomes.label])
        .mean()
        .reset_index(name="approval_rate")
    )
    attack = outcome_rate.loc[outcome_rate.label.eq(1), "approval_rate"]
    legitimate = outcome_rate.loc[outcome_rate.label.eq(0), "approval_rate"]
    assert attack.max() >= legitimate.quantile(0.25)
    assert legitimate.min() <= attack.quantile(0.75)
    assert (
        outcomes.loc[outcomes.label.eq(1), "authorization_result"].eq("approved").any()
    )
    assert (
        outcomes.loc[outcomes.label.eq(0), "authorization_result"].eq("declined").any()
    )


def test_frozen_replay_has_exact_contract_and_no_metadata() -> None:
    bundle = PBRSSV1Generator(fixture_config()).generate()
    features = build_feature_table_v3(bundle["raw_events"], bundle["labels"])
    model_columns = tuple(column for column in features if column in MODEL_FEATURES_V3)
    assert model_columns == MODEL_FEATURES_V3
    assert len(model_columns) == 44
    forbidden = {
        "scenario",
        "population",
        "label",
        "merchant_id",
        "device_id",
        "actor_id",
        "leakage_group_id",
        "counterfactual_role",
    }
    assert forbidden.isdisjoint(model_columns)
    assert features.loc[:, list(model_columns)].notna().all().all()


def test_current_snapshot_is_independent_of_its_future_outcome() -> None:
    bundle = PBRSSV1Generator(fixture_config()).generate()
    raw = bundle["raw_events"].copy()
    first_request = raw.loc[
        raw.event_type.eq("authorization_request"), "request_id"
    ].iloc[0]
    before = build_feature_table_v3(raw, bundle["labels"])
    outcome = raw.request_id.eq(first_request) & raw.event_type.eq(
        "authorization_outcome"
    )
    raw.loc[outcome, "authorization_result"] = "approved"
    raw.loc[outcome, "failure_reason"] = None
    after = build_feature_table_v3(raw, bundle["labels"])
    left = before.loc[before.request_id.eq(first_request), list(MODEL_FEATURES_V3)]
    right = after.loc[after.request_id.eq(first_request), list(MODEL_FEATURES_V3)]
    pd.testing.assert_frame_equal(
        left.reset_index(drop=True), right.reset_index(drop=True)
    )


def test_generator_source_has_no_model_policy_or_metric_access() -> None:
    source = (
        (ROOT / "src/card_testing_sentinel/ml/pbrss_v1_generator.py")
        .read_text()
        .lower()
    )
    forbidden = (
        "risk_model_v3_1",
        "artifacts/model_v3_1",
        "candidate_metrics",
        "targeted_ablations",
        "policy.engine",
        "ml.metrics",
        "score_frame",
    )
    assert not any(term in source for term in forbidden)
