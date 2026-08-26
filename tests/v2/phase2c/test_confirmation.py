from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from card_testing_sentinel.v2.phase2c.confirmation import (
    BASE_PERFORMANCE_ARTIFACTS,
    generate_confirmation_frames,
    refuse_blind_access,
    verify_confirmation_lifecycle,
    verify_one_time_state,
)


def _dataset(data_dir: Path, *, seed: int = 20260827):
    data_dir.mkdir(parents=True)
    payload = b"fixture"
    (data_dir / "raw_events.csv").write_bytes(payload)
    manifest = {
        "seed": seed,
        "accepted": True,
        "generation_count": 1,
        "files": {"raw_events.csv": hashlib.sha256(payload).hexdigest()},
        "structural_validation": {"status": "passed"},
    }
    (data_dir / "manifest.json").write_text(json.dumps(manifest))


def test_pre_generation_success_and_failure(tmp_path: Path):
    data = tmp_path / "data"
    artifacts = tmp_path / "artifacts"
    assert verify_one_time_state(
        data_dir=data,
        artifact_dir=artifacts,
        state="pre_generation",
        expected_seed=20260827,
    )["passed"]
    data.mkdir()
    with pytest.raises(PermissionError, match="absent"):
        verify_one_time_state(
            data_dir=data,
            artifact_dir=artifacts,
            state="pre_generation",
            expected_seed=20260827,
        )


def test_post_generation_matching_drift_seed_and_second_access(tmp_path: Path):
    data = tmp_path / "data"
    artifacts = tmp_path / "artifacts"
    _dataset(data)
    assert verify_one_time_state(
        data_dir=data,
        artifact_dir=artifacts,
        state="post_generation_pre_scoring",
        expected_seed=20260827,
    )["passed"]
    (data / "raw_events.csv").write_text("drift")
    with pytest.raises(PermissionError, match="drift"):
        verify_one_time_state(
            data_dir=data,
            artifact_dir=artifacts,
            state="post_generation_pre_scoring",
            expected_seed=20260827,
        )
    data = tmp_path / "wrong_seed"
    _dataset(data, seed=1)
    with pytest.raises(PermissionError, match="seed"):
        verify_one_time_state(
            data_dir=data,
            artifact_dir=artifacts,
            state="post_generation_pre_scoring",
            expected_seed=20260827,
        )
    good = tmp_path / "good"
    _dataset(good)
    artifacts.mkdir()
    (artifacts / "access_ledger.json").write_text("{}")
    with pytest.raises(PermissionError, match="second"):
        verify_one_time_state(
            data_dir=good,
            artifact_dir=artifacts,
            state="post_generation_pre_scoring",
            expected_seed=20260827,
        )


def test_metrics_without_ledger_and_ledger_without_outputs_refused(tmp_path: Path):
    data = tmp_path / "data"
    artifacts = tmp_path / "artifacts"
    _dataset(data)
    artifacts.mkdir()
    (artifacts / "candidate_results.csv").write_text("x")
    with pytest.raises(PermissionError, match="without a ledger"):
        verify_one_time_state(
            data_dir=data,
            artifact_dir=artifacts,
            state="post_generation_pre_scoring",
            expected_seed=20260827,
        )
    (artifacts / "access_ledger.json").write_text(
        json.dumps({"scoring_attempt": 1, "status": "completed_blocked"})
    )
    with pytest.raises(PermissionError, match="incomplete"):
        verify_one_time_state(
            data_dir=data,
            artifact_dir=artifacts,
            state="post_scoring",
            expected_seed=20260827,
        )


def test_post_scoring_success_for_complete_blocked_result(tmp_path: Path):
    data = tmp_path / "data"
    artifacts = tmp_path / "artifacts"
    _dataset(data)
    artifacts.mkdir()
    for name in BASE_PERFORMANCE_ARTIFACTS:
        path = artifacts / name
        if name == "access_ledger.json":
            path.write_text(
                json.dumps({"scoring_attempt": 1, "status": "completed_blocked"})
            )
        elif name == "feasibility.json":
            path.write_text(json.dumps({"status": "completed_blocked"}))
        else:
            path.write_text("fixture")
    assert verify_one_time_state(
        data_dir=data,
        artifact_dir=artifacts,
        state="post_scoring",
        expected_seed=20260827,
    )["passed"]


def test_wrong_seed_generation_blind_and_pre_freeze_access_refused(tmp_path: Path):
    with pytest.raises(PermissionError, match="seed"):
        generate_confirmation_frames({"seed": 1})
    with pytest.raises(PermissionError, match="blind"):
        refuse_blind_access()
    with pytest.raises(FileNotFoundError, match="freeze"):
        verify_confirmation_lifecycle(root=tmp_path, state="pre_generation")
