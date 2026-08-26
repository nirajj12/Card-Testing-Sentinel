import hashlib
import json
import shutil
from pathlib import Path

import pandas as pd
import pytest

from card_testing_sentinel.v2.phase3.contracts import SCENARIO_COUNTS
from card_testing_sentinel.v2.phase3.lifecycle import (
    HISTORICAL_INPUTS,
    PHASE3_INPUTS,
    _append_ledger,
    _write_new_ledger,
    accept_scoring_once,
    assert_real_outputs_absent,
    build_pre_access_freeze,
    complete_scoring_ledger,
    generate_blind_frames,
    refuse_if_scoring_accessed,
    sha256_file,
    validate_blind_frames,
    verify_dataset_manifest,
    verify_lifecycle,
    verify_pre_access_freeze,
    write_blind_bundle,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True))


def test_pre_generation_and_transition_append_only(tmp_path):
    ledger = _write_new_ledger(tmp_path)
    assert ledger["current_state"] == "pre_generation"
    advanced = _append_ledger(
        tmp_path,
        "post_generation_pre_scoring",
        dataset_manifest_sha256="abc",
    )
    assert [row["state"] for row in advanced["transitions"]] == [
        "pre_generation",
        "post_generation_pre_scoring",
    ]
    assert advanced["transitions"][0] == ledger["transitions"][0]
    with pytest.raises(PermissionError, match="invalid"):
        _append_ledger(tmp_path, "pre_generation")


def test_second_scoring_access_refused_before_dataset_read(tmp_path):
    _write_json(
        tmp_path / "artifacts/v2/phase3/blind/access_ledger.json",
        {"accepted_scoring_attempts": 1},
    )
    with pytest.raises(PermissionError, match="second blind"):
        refuse_if_scoring_accessed(tmp_path)


def test_dataset_hash_drift_detectable(tmp_path):
    path = tmp_path / "raw_events.csv"
    path.write_text("original\n")
    digest = sha256_file(path)
    path.write_text("drift\n")
    assert sha256_file(path) != digest


def test_pre_access_absence_guard(tmp_path):
    assert_real_outputs_absent(tmp_path)
    result = tmp_path / "artifacts/v2/phase3/blind/final_blind_metrics.json"
    result.parent.mkdir(parents=True)
    result.write_text("{}")
    with pytest.raises(PermissionError, match="already exists"):
        assert_real_outputs_absent(tmp_path)


def test_freeze_drift_refused(tmp_path):
    protected = tmp_path / "protected.txt"
    protected.write_text("frozen")
    freeze = tmp_path / "artifacts/v2/phase3/blind/pre_access_freeze.json"
    payload = {
        "blind_seed": 20260828,
        "expected_policy_sha256": (
            "9afeba2df176c87287e86ff0402ef96b58e9386608d003b5702986be02b6ae95"
        ),
        "expected_policies_evaluated": 1,
        "protected_hashes": {"protected.txt": sha256_file(protected)},
    }
    _write_json(freeze, payload)
    freeze.with_suffix(".sha256").write_text(sha256_file(freeze))
    protected.write_text("drift")
    with pytest.raises(PermissionError, match="frozen input drift"):
        verify_pre_access_freeze(tmp_path)


def test_dataset_manifest_refuses_data_drift(tmp_path):
    freeze = tmp_path / "artifacts/v2/phase3/blind/pre_access_freeze.json"
    _write_json(freeze, {})
    data = tmp_path / "data/v2/phase3/blind"
    data.mkdir(parents=True)
    raw = data / "raw_events.csv"
    contract = data / "device_contract.csv"
    raw.write_text("raw")
    contract.write_text("contract")
    payload = {
        "seed": 20260828,
        "generation_count": 1,
        "accepted": True,
        "pre_access_freeze_sha256": sha256_file(freeze),
        "structural_validation": {"status": "passed"},
        "files": {
            "raw_events.csv": sha256_file(raw),
            "device_contract.csv": sha256_file(contract),
        },
    }
    _write_json(data / "manifest.json", payload)
    artifact = tmp_path / "artifacts/v2/phase3/blind/dataset_manifest.json"
    _write_json(artifact, payload)
    raw.write_text("drift")
    with pytest.raises(PermissionError, match="dataset hash drift"):
        verify_dataset_manifest(tmp_path)


def test_post_scoring_missing_artifacts_refused(tmp_path, monkeypatch):
    ledger = tmp_path / "artifacts/v2/phase3/blind/access_ledger.json"
    _write_json(
        ledger,
        {"current_state": "post_scoring", "accepted_scoring_attempts": 1},
    )
    monkeypatch.setattr(
        "card_testing_sentinel.v2.phase3.lifecycle.verify_pre_access_freeze",
        lambda _root: {},
    )
    monkeypatch.setattr(
        "card_testing_sentinel.v2.phase3.lifecycle.verify_dataset_manifest",
        lambda _root: {},
    )
    with pytest.raises(PermissionError, match="outputs incomplete"):
        verify_lifecycle(tmp_path, "post_scoring")


def test_complete_pre_access_freeze_on_tmp_fixture(tmp_path, monkeypatch):
    for relative in (*HISTORICAL_INPUTS, *PHASE3_INPUTS):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"fixture:{relative}\n")
    shutil.copy2(
        "configs/v2/phase3/blind.yaml",
        tmp_path / "configs/v2/phase3/blind.yaml",
    )
    monkeypatch.setattr(
        "card_testing_sentinel.v2.phase3.lifecycle.verify_correction_chain",
        lambda _root: {},
    )
    monkeypatch.setattr(
        "card_testing_sentinel.v2.phase3.lifecycle.verify_resumed_post_scoring",
        lambda _root: {},
    )
    monkeypatch.setattr(
        "card_testing_sentinel.v2.phase3.lifecycle._verify_authoritative_hashes",
        lambda _root: None,
    )
    path, digest = build_pre_access_freeze(tmp_path)
    assert path.is_file()
    assert digest == sha256_file(path)
    assert verify_pre_access_freeze(tmp_path)["real_blind_paths_absent_at_freeze"]
    with pytest.raises(FileExistsError, match="already exists"):
        build_pre_access_freeze(tmp_path)


def test_tmp_generation_bundle_and_access_acceptance(tmp_path, monkeypatch):
    freeze = tmp_path / "artifacts/v2/phase3/blind/pre_access_freeze.json"
    _write_json(freeze, {})
    freeze.with_suffix(".sha256").write_text(sha256_file(freeze))
    raw = pd.DataFrame(
        [
            {
                "event_id": "e1",
                "request_id": "r1",
                "event_sequence": 1,
                "timestamp": "2026-07-01T00:00:00+00:00",
                "event_type": "authorization_request",
                "device_id": "d1",
                "session_id": "s1",
                "label": 0,
                "population": "normal",
                "attack_subtype": None,
                "scenario_tag": "normal_standard",
            }
        ]
    )
    contract = pd.DataFrame(
        [
            {
                "device_id": "d1",
                "label": 0,
                "population": "normal",
                "attack_subtype": None,
                "scenario_tag": "normal_standard",
            }
        ]
    )
    config = {"version": "fixture", "seed": 20260828}
    config_path = tmp_path / "configs/v2/phase3/blind.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("version: fixture\n")
    generator_path = tmp_path / "src/card_testing_sentinel/v2/data/generator.py"
    generator_path.parent.mkdir(parents=True)
    generator_path.write_text("# fixture\n")
    for relative in (
        "data/v2/development/raw_events.csv",
        "data/v2/phase2b/fresh_validation/raw_events.csv",
        "data/v2/phase2c/confirmation_validation/raw_events.csv",
    ):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        raw.to_csv(target, index=False)
    monkeypatch.setattr(
        "card_testing_sentinel.v2.phase3.lifecycle.verify_pre_access_freeze",
        lambda _root: {},
    )
    monkeypatch.setattr(
        "card_testing_sentinel.v2.phase3.lifecycle.load_blind_config",
        lambda _root: config,
    )
    monkeypatch.setattr(
        "card_testing_sentinel.v2.phase3.lifecycle.generate_blind_frames",
        lambda _config: (raw, contract),
    )
    monkeypatch.setattr(
        "card_testing_sentinel.v2.phase3.lifecycle.validate_blind_frames",
        lambda *_args: {"status": "passed"},
    )
    manifest = write_blind_bundle(tmp_path)
    assert manifest["generation_count"] == 1
    assert verify_dataset_manifest(tmp_path)["seed"] == 20260828
    assert verify_lifecycle(tmp_path, "post_generation_pre_scoring")["passed"]
    accepted = accept_scoring_once(tmp_path)
    assert accepted["accepted_scoring_attempts"] == 1
    with pytest.raises(PermissionError, match="second blind"):
        refuse_if_scoring_accessed(tmp_path)
    completed = complete_scoring_ledger(
        tmp_path, "blind_completed_passed", {"fixture": "digest"}
    )
    assert completed["current_state"] == "post_scoring"


def test_fixture_generator_is_deterministic_and_namespaced():
    config = {
        "seed": 20260828,
        "start_timestamp": "2026-07-01T00:00:00+00:00",
        "currency": "USD",
        "validation_fraction": 0.0,
        "device_counts": {name: 1 for name in SCENARIO_COUNTS},
        "identifier_namespace": "blind_20260828",
    }
    first_raw, first_contract = generate_blind_frames(config)
    second_raw, second_contract = generate_blind_frames(config)
    assert hashlib.sha256(first_raw.to_csv(index=False).encode()).digest() == (
        hashlib.sha256(second_raw.to_csv(index=False).encode()).digest()
    )
    pd.testing.assert_frame_equal(first_contract, second_contract)
    assert first_raw.event_id.str.startswith("blind_20260828_").all()


def test_structural_validator_rejects_wrong_denominators():
    with pytest.raises(RuntimeError, match="scenario denominators"):
        validate_blind_frames(pd.DataFrame(), pd.DataFrame({"scenario_tag": []}), {})


def test_missing_ledger_is_not_silently_invented(tmp_path):
    assert not (tmp_path / "artifacts/v2/phase3/blind/access_ledger.json").exists()
