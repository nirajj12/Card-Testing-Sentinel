from __future__ import annotations

import copy
import json
from pathlib import Path

import pandas as pd
import yaml

from card_testing_sentinel.features.batch_v3 import build_feature_table_v3
from card_testing_sentinel.features.specification_v3 import MODEL_FEATURES_V3
from card_testing_sentinel.ml.pbrss_v1_generator import (
    PBRSSV1Generator,
    build_manifest,
)

ROOT = Path(__file__).resolve().parents[2]


def fixture_config(devices: int = 48) -> dict:
    config = yaml.safe_load((ROOT / "configs/post_blind_stress_v1.yaml").read_text())
    config["population"]["devices"] = devices
    config["population"]["target_requests"] = devices * 4
    return config


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
