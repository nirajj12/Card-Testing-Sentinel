"""Pre-access tests for the one-time fresh-validation generator and guard."""

import json
from pathlib import Path

import pandas as pd
import pytest
import yaml

from card_testing_sentinel.v2.phase2b import fresh_validation as fresh


def _config(count=2):
    return {
        "version": "test-fresh-1",
        "seed": fresh.FRESH_SEED,
        "start_timestamp": "2026-03-01T00:00:00+00:00",
        "currency": "USD",
        "validation_fraction": 0.0,
        "device_counts": {
            "normal_standard": count,
            "normal_bad_luck": count,
            "flash_standard": count,
            "flash_hard_retry": count,
            "attack_burst": count,
            "attack_evasive": count,
            "attack_patient": count,
        },
        "expected_counts": {
            "devices": 7 * count,
            "legitimate_devices": 4 * count,
            "attacker_devices": 3 * count,
        },
        "identifier_namespace": "fixture_fv",
    }


def _empty_historical(raw):
    return raw.iloc[0:0].copy()


def test_generation_is_deterministic_disjoint_causal_and_linked():
    config = _config()
    first_raw, first_contract = fresh.generate_fresh_frames(config)
    second_raw, second_contract = fresh.generate_fresh_frames(config)
    pd.testing.assert_frame_equal(first_raw, second_raw)
    pd.testing.assert_frame_equal(first_contract, second_contract)
    report = fresh.validate_fresh_frames(
        first_raw, first_contract, config, _empty_historical(first_raw)
    )
    assert report["status"] == "passed"
    assert report["identifier_overlap_counts"] == {
        name: 0 for name in fresh.IDENTIFIER_COLUMNS
    }
    assert report["generation_columns_in_model_allowlist"] == []
    ordered = first_raw.sort_values(
        ["timestamp", "event_sequence"], kind="mergesort"
    ).reset_index(drop=True)
    pd.testing.assert_frame_equal(first_raw, ordered)
    assert first_raw.event_id.is_unique


def test_generation_seed_and_overlap_fail_closed():
    config = _config()
    raw, contract = fresh.generate_fresh_frames(config)
    wrong = dict(config, seed=1)
    with pytest.raises(PermissionError, match="seed"):
        fresh.generate_fresh_frames(wrong)
    with pytest.raises(RuntimeError, match="overlap"):
        fresh.validate_fresh_frames(raw, contract, config, raw)


def _fake_root(tmp_path: Path, monkeypatch):
    root = tmp_path / "repo"
    (root / "data/v2/development").mkdir(parents=True)
    config = _config()
    config_path = root / "configs/v2/phase2b/fresh_validation.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(yaml.safe_dump(config, sort_keys=False))
    raw, _ = fresh.generate_fresh_frames(config)
    raw.iloc[0:0].to_csv(root / "data/v2/development/raw_events.csv", index=False)
    pd.DataFrame(columns=["device_id", "split"]).to_csv(
        root / "data/v2/development/device_splits.csv", index=False
    )
    monkeypatch.setattr(fresh, "verify_training_freeze_file", lambda *_a, **_k: {})
    monkeypatch.setattr(
        fresh,
        "verify_execution_freeze",
        lambda *_a, **_k: {"fresh_validation_seed": fresh.FRESH_SEED},
    )
    execution = root / fresh.EXECUTION_FREEZE_RELATIVE_PATH
    execution.parent.mkdir(parents=True)
    execution.write_text("fixture execution freeze\n")
    training = root / "artifacts/v2/phase2b/training/freeze"
    training.mkdir(parents=True)
    (training / "training_freeze.json").write_text("fixture training freeze\n")
    return root, config_path


def test_atomic_bundle_refuses_existing_and_cleans_partial(tmp_path, monkeypatch):
    root, config_path = _fake_root(tmp_path, monkeypatch)
    output = root / fresh.FRESH_RELATIVE_PATH
    with pytest.raises(RuntimeError, match="injected"):
        fresh.write_fresh_validation_bundle(
            root=root,
            config_path=config_path,
            output_dir=output,
            failure_hook=lambda: (_ for _ in ()).throw(RuntimeError("injected")),
        )
    assert not output.exists()
    assert not list(output.parent.glob(".fresh-validation-*"))
    manifest = fresh.write_fresh_validation_bundle(
        root=root,
        config_path=config_path,
        output_dir=output,
        created_utc="2026-08-26T00:00:00+00:00",
    )
    assert manifest["accepted"]
    assert set(path.name for path in output.iterdir()) == {
        "raw_events.csv",
        "device_contract.csv",
        "manifest.json",
    }
    with pytest.raises(FileExistsError, match="regeneration"):
        fresh.write_fresh_validation_bundle(
            root=root, config_path=config_path, output_dir=output
        )


def test_manifest_wrong_seed_and_hash_drift_refuse(tmp_path):
    output = tmp_path / "data"
    output.mkdir()
    (output / "raw_events.csv").write_text("x\n1\n")
    manifest = {
        "seed": 1,
        "accepted": True,
        "files": {"raw_events.csv": fresh.sha256_file(output / "raw_events.csv")},
    }
    (output / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(PermissionError, match="seed"):
        fresh.verify_dataset_manifest(output)
    manifest["seed"] = fresh.FRESH_SEED
    (output / "manifest.json").write_text(json.dumps(manifest))
    (output / "raw_events.csv").write_text("changed\n")
    with pytest.raises(PermissionError, match="hash drift"):
        fresh.verify_dataset_manifest(output)


def test_execution_freeze_detects_source_drift(tmp_path):
    root = tmp_path / "repo"
    source = root / "source.py"
    source.parent.mkdir()
    source.write_text("stable\n")
    freeze_path = root / "artifacts/execution_freeze.json"
    path, _ = fresh.write_execution_freeze(
        root=root,
        freeze_path=freeze_path,
        protected_paths=("source.py",),
        payload={"fresh_validation_seed": fresh.FRESH_SEED, "candidate_count": 78},
    )
    assert fresh.verify_execution_freeze(path, root=root)["candidate_count"] == 78
    source.write_text("drift\n")
    with pytest.raises(PermissionError, match="methodology drift"):
        fresh.verify_execution_freeze(path, root=root)


def test_access_guard_records_once_and_blind_is_always_refused(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    output = root / fresh.FRESH_RELATIVE_PATH
    output.mkdir(parents=True)
    pd.DataFrame({"event_id": ["e"]}).to_csv(output / "raw_events.csv", index=False)
    pd.DataFrame({"device_id": ["d"]}).to_csv(
        output / "device_contract.csv", index=False
    )
    (output / "manifest.json").write_text("{}\n")
    execution = root / fresh.EXECUTION_FREEZE_RELATIVE_PATH
    execution.parent.mkdir(parents=True)
    execution.write_text("execution\n")
    (root / fresh.AMENDMENT_RELATIVE_PATH).write_text("amendment\n")
    monkeypatch.setattr(
        fresh,
        "verify_validation_lifecycle",
        lambda **_kwargs: {
            "execution": {
                "training_freeze_sha256": "training",
                "fresh_validation_seed": fresh.FRESH_SEED,
            }
        },
    )
    monkeypatch.setattr(
        fresh,
        "verify_dataset_manifest",
        lambda *_a, **_k: {
            "execution_freeze_sha256": fresh.sha256_file(execution),
            "seed": fresh.FRESH_SEED,
        },
    )
    ledger = root / fresh.ACCESS_LEDGER_RELATIVE_PATH
    _, _, recorded = fresh.open_fresh_validation_once(
        root=root,
        output_dir=output,
        ledger_path=ledger,
        started_utc="2026-08-26T00:00:00+00:00",
    )
    assert recorded["scoring_attempt"] == 1
    with pytest.raises(PermissionError, match="second scoring"):
        fresh.open_fresh_validation_once(
            root=root, output_dir=output, ledger_path=ledger
        )
    with pytest.raises(PermissionError, match="blind"):
        fresh.refuse_blind_access(root / "blind")


def test_access_guard_refuses_unverified_training_freeze(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    output = root / fresh.FRESH_RELATIVE_PATH
    output.mkdir(parents=True)
    ledger = root / fresh.ACCESS_LEDGER_RELATIVE_PATH
    monkeypatch.setattr(
        fresh,
        "verify_validation_lifecycle",
        lambda **_kwargs: (_ for _ in ()).throw(PermissionError("training drift")),
    )
    with pytest.raises(PermissionError, match="training drift"):
        fresh.open_fresh_validation_once(
            root=root, output_dir=output, ledger_path=ledger
        )
    assert not ledger.exists()


def _lifecycle_fixture(tmp_path: Path, monkeypatch):
    root = tmp_path / "repo"
    data = root / fresh.FRESH_RELATIVE_PATH
    artifacts = root / fresh.EXECUTION_FREEZE_RELATIVE_PATH.parent
    artifacts.mkdir(parents=True)
    monkeypatch.setattr(
        fresh, "_verify_training_boundary", lambda *_a, **_k: {"verified": True}
    )
    monkeypatch.setattr(fresh, "verify_execution_freeze", lambda *_a, **_k: {})
    monkeypatch.setattr(
        fresh,
        "verify_execution_amendment",
        lambda *_a, **_k: {"training_freeze_sha256": "training"},
    )
    return root, data, artifacts


def _accepted_fixture(data: Path, monkeypatch, *, seed=fresh.FRESH_SEED):
    data.mkdir(parents=True)
    (data / "raw_events.csv").write_text("event_id\ne1\n")
    (data / "device_contract.csv").write_text("device_id\nd1\n")
    manifest = {
        "seed": seed,
        "accepted": True,
        "files": {
            name: fresh.sha256_file(data / name)
            for name in ("raw_events.csv", "device_contract.csv")
        },
        "structural_validation": {"status": "passed"},
    }
    (data / "manifest.json").write_text(json.dumps(manifest))
    monkeypatch.setattr(
        fresh, "FRESH_MANIFEST_SHA256", fresh.sha256_file(data / "manifest.json")
    )


def test_lifecycle_pre_generation_success_and_failure(tmp_path, monkeypatch):
    root, data, artifacts = _lifecycle_fixture(tmp_path, monkeypatch)
    result = fresh.verify_validation_lifecycle(
        root=root,
        state="pre_generation",
        data_dir=data,
        artifact_dir=artifacts,
    )
    assert result["passed"]
    data.mkdir(parents=True)
    with pytest.raises(PermissionError, match="absent"):
        fresh.verify_validation_lifecycle(
            root=root,
            state="pre_generation",
            data_dir=data,
            artifact_dir=artifacts,
        )


def test_lifecycle_post_generation_matching_hashes_and_second_attempt_refusal(
    tmp_path, monkeypatch
):
    root, data, artifacts = _lifecycle_fixture(tmp_path, monkeypatch)
    _accepted_fixture(data, monkeypatch)
    result = fresh.verify_validation_lifecycle(
        root=root,
        state="post_generation_pre_scoring",
        data_dir=data,
        artifact_dir=artifacts,
    )
    assert result["dataset"]["seed"] == fresh.FRESH_SEED
    (artifacts / "access_ledger.json").write_text("{}\n")
    with pytest.raises(PermissionError, match="second scoring"):
        fresh.verify_validation_lifecycle(
            root=root,
            state="post_generation_pre_scoring",
            data_dir=data,
            artifact_dir=artifacts,
        )


def test_lifecycle_post_generation_refuses_dataset_drift_and_wrong_seed(
    tmp_path, monkeypatch
):
    root, data, artifacts = _lifecycle_fixture(tmp_path, monkeypatch)
    _accepted_fixture(data, monkeypatch)
    (data / "raw_events.csv").write_text("drift\n")
    with pytest.raises(PermissionError, match="hash drift"):
        fresh.verify_validation_lifecycle(
            root=root,
            state="post_generation_pre_scoring",
            data_dir=data,
            artifact_dir=artifacts,
        )
    data.parent.joinpath("unused").mkdir(parents=True)
    for path in data.iterdir():
        path.unlink()
    data.rmdir()
    _accepted_fixture(data, monkeypatch, seed=1)
    with pytest.raises(PermissionError, match="seed"):
        fresh.verify_validation_lifecycle(
            root=root,
            state="post_generation_pre_scoring",
            data_dir=data,
            artifact_dir=artifacts,
        )


def test_lifecycle_refuses_metrics_without_ledger_and_incomplete_post_scoring(
    tmp_path, monkeypatch
):
    root, data, artifacts = _lifecycle_fixture(tmp_path, monkeypatch)
    _accepted_fixture(data, monkeypatch)
    (artifacts / "static_model_metrics.json").write_text("{}\n")
    with pytest.raises(PermissionError, match="without a scoring ledger"):
        fresh.verify_validation_lifecycle(
            root=root,
            state="post_generation_pre_scoring",
            data_dir=data,
            artifact_dir=artifacts,
        )
    (artifacts / "access_ledger.json").write_text(
        json.dumps({"scoring_attempt": 1, "status": "completed_blocked"})
    )
    with pytest.raises(PermissionError, match="incomplete"):
        fresh.verify_validation_lifecycle(
            root=root,
            state="post_scoring",
            data_dir=data,
            artifact_dir=artifacts,
        )


def test_lifecycle_post_scoring_success(tmp_path, monkeypatch):
    root, data, artifacts = _lifecycle_fixture(tmp_path, monkeypatch)
    _accepted_fixture(data, monkeypatch)
    for name in fresh.PERFORMANCE_ARTIFACTS:
        (artifacts / name).write_text("fixture\n")
    (artifacts / "access_ledger.json").write_text(
        json.dumps({"scoring_attempt": 1, "status": "completed_blocked"})
    )
    (artifacts / "feasibility.json").write_text(
        json.dumps({"status": "completed_blocked"})
    )
    result = fresh.verify_validation_lifecycle(
        root=root,
        state="post_scoring",
        data_dir=data,
        artifact_dir=artifacts,
    )
    assert result["passed"]
