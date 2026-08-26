"""Gate 7 (corrective pass, coverage raise): fills the remaining gaps in
src/card_testing_sentinel/v2/evaluation/access.py not already covered by
tests/v2/phase2b/test_gate6_decision_critical_coverage.py or
tests/v2/phase2b/test_gate_d_focused.py (verify_training_freeze's missing/
hash-mismatch paths, and open_validation's missing-freeze fail-closed path
are already covered there and are not duplicated here).

Every test monkeypatches only filesystem paths (ROOT / DEVELOPMENT_DIR /
FREEZE_PATH) or an already-separately-tested helper (verify_training_freeze)
-- never the boundary-checking decision logic actually under test in each
function.
"""

import json

import pandas as pd
import pytest

from card_testing_sentinel.v2.evaluation import access

# ---------------------------------------------------------------------------
# verify_phase1_protected_inputs / verify_v1_release fail-closed on tamper.
# ---------------------------------------------------------------------------


def test_verify_phase1_protected_inputs_fails_closed_on_modified_input(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(access, "ROOT", tmp_path)
    # Recreate every protected relative path with WRONG content so every
    # hash observed differs from the frozen expected hash.
    for name in access.PHASE1_PROTECTED_HASHES:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("tampered content, not the frozen bytes")
    with pytest.raises(RuntimeError, match="Phase 1 protected inputs changed"):
        access.verify_phase1_protected_inputs()


def test_verify_phase1_protected_inputs_fails_closed_on_missing_input(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(access, "ROOT", tmp_path)
    # None of the protected files exist under this empty tmp_path root.
    with pytest.raises(FileNotFoundError):
        access.verify_phase1_protected_inputs()


def test_verify_v1_release_fails_closed_on_modified_release_entry(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(access, "ROOT", tmp_path)
    manifest_dir = tmp_path / "docs/v1"
    manifest_dir.mkdir(parents=True)
    target = tmp_path / "frozen_release_file.txt"
    target.write_text("original frozen bytes")
    original_digest = access.sha256_file(target)
    (manifest_dir / "release_manifest.sha256").write_text(
        f"{original_digest}  frozen_release_file.txt\n"
    )
    # Now tamper with the release entry after the manifest was written.
    target.write_text("tampered bytes, not what the manifest expects")
    with pytest.raises(RuntimeError, match="V1 protected release entry changed"):
        access.verify_v1_release()


def test_verify_v1_release_accepts_an_unmodified_entry(tmp_path, monkeypatch):
    monkeypatch.setattr(access, "ROOT", tmp_path)
    manifest_dir = tmp_path / "docs/v1"
    manifest_dir.mkdir(parents=True)
    target = tmp_path / "frozen_release_file.txt"
    target.write_text("original frozen bytes")
    digest = access.sha256_file(target)
    (manifest_dir / "release_manifest.sha256").write_text(
        f"# a comment line should be skipped\n{digest}  *frozen_release_file.txt\n"
    )
    entries = access.verify_v1_release()
    assert entries == {"frozen_release_file.txt": digest}


# ---------------------------------------------------------------------------
# load_training_features / load_training_raw_events / _split_ids
# ---------------------------------------------------------------------------


def _write_small_development_fixture(tmp_path, monkeypatch, n_train=4, n_other=2):
    development_dir = tmp_path / "data/v2/development"
    development_dir.mkdir(parents=True)
    monkeypatch.setattr(access, "DEVELOPMENT_DIR", development_dir)
    device_ids = [f"device-{i}" for i in range(n_train + n_other)]
    splits = pd.DataFrame(
        {
            "device_id": device_ids,
            "split": ["train"] * n_train + ["validation"] * n_other,
        }
    )
    splits.to_csv(development_dir / "device_splits.csv", index=False)
    features = pd.DataFrame(
        {
            "device_id": device_ids,
            "value": range(len(device_ids)),
        }
    )
    features.to_csv(development_dir / "events_with_features.csv", index=False)
    raw = pd.DataFrame(
        {
            "device_id": device_ids + [device_ids[0]],  # one device with 2 raw rows
            "event_type": ["authorization_request"] * (len(device_ids) + 1),
        }
    )
    raw.to_csv(development_dir / "raw_events.csv", index=False)
    return development_dir, device_ids[:n_train], device_ids[n_train:]


def test_split_ids_returns_only_devices_in_the_requested_split(tmp_path, monkeypatch):
    _write_small_development_fixture(tmp_path, monkeypatch, n_train=4, n_other=2)
    train_ids = access._split_ids("train")
    validation_ids = access._split_ids("validation")
    assert len(train_ids) == 4
    assert len(validation_ids) == 2
    assert train_ids.isdisjoint(validation_ids)


def test_load_training_features_fails_closed_on_row_count_boundary_mismatch(
    tmp_path, monkeypatch
):
    # This small fixture can never satisfy the frozen boundary check
    # (exactly 21,338 rows) -- it must fail closed rather than silently
    # returning a wrong-shaped training frame.
    _write_small_development_fixture(tmp_path, monkeypatch)
    with pytest.raises(RuntimeError, match="training feature boundary failed"):
        access.load_training_features()


def test_load_training_raw_events_filters_to_train_devices_only(tmp_path, monkeypatch):
    _, train_ids, other_ids = _write_small_development_fixture(tmp_path, monkeypatch)
    raw = access.load_training_raw_events()
    assert set(raw.device_id) <= set(train_ids)
    assert set(raw.device_id).isdisjoint(other_ids)
    # The duplicated raw row for the first training device must survive the
    # filter (load_training_raw_events does not deduplicate raw events).
    assert (raw.device_id == train_ids[0]).sum() == 2


# ---------------------------------------------------------------------------
# verify_training_freeze: frozen-artifact tamper and validation_sealed=False.
# ---------------------------------------------------------------------------


def _write_valid_freeze(tmp_path, monkeypatch, protected_relative_path, extra=None):
    monkeypatch.setattr(access, "ROOT", tmp_path)
    freeze_dir = tmp_path / "artifacts/v2/training"
    freeze_dir.mkdir(parents=True)
    freeze_path = freeze_dir / "training_freeze.json"
    digest_path = freeze_dir / "training_freeze.sha256"
    monkeypatch.setattr(access, "FREEZE_PATH", freeze_path)
    monkeypatch.setattr(access, "FREEZE_DIGEST_PATH", digest_path)
    monkeypatch.setattr(access, "PHASE1_PROTECTED_HASHES", {})

    protected_target = tmp_path / protected_relative_path
    protected_target.parent.mkdir(parents=True, exist_ok=True)
    protected_target.write_text("frozen artifact bytes")
    frozen_digest = access.sha256_file(protected_target)

    freeze = {
        "validation_sealed": True,
        "phase2_frozen_artifact_hashes": {protected_relative_path: frozen_digest},
    }
    if extra:
        freeze.update(extra)
    freeze_path.write_text(json.dumps(freeze))
    digest_path.write_text(access.sha256_file(freeze_path) + "\n")
    return freeze_path, protected_target


def test_verify_training_freeze_fails_closed_when_a_frozen_artifact_is_modified(
    tmp_path, monkeypatch
):
    _freeze_path, protected_target = _write_valid_freeze(
        tmp_path, monkeypatch, "artifacts/v2/models/calibrated_model.joblib"
    )
    # Tamper with the frozen artifact after the freeze was sealed.
    protected_target.write_text("someone modified the frozen model bytes")
    with pytest.raises(PermissionError, match="frozen Phase 2 artifact changed"):
        access.verify_training_freeze()


def test_verify_training_freeze_fails_closed_when_validation_not_attested_sealed(
    tmp_path, monkeypatch
):
    freeze_path, _target = _write_valid_freeze(
        tmp_path,
        monkeypatch,
        "artifacts/v2/models/calibrated_model.joblib",
        extra={"validation_sealed": False},
    )
    # Recompute the digest to match the edited freeze content.
    monkeypatch.setattr(
        access,
        "FREEZE_DIGEST_PATH",
        access.FREEZE_PATH.parent / "training_freeze.sha256",
    )
    access.FREEZE_DIGEST_PATH.write_text(access.sha256_file(freeze_path) + "\n")
    with pytest.raises(PermissionError, match="validation stayed sealed"):
        access.verify_training_freeze()


def test_verify_training_freeze_accepts_a_genuinely_valid_freeze(tmp_path, monkeypatch):
    _write_valid_freeze(
        tmp_path, monkeypatch, "artifacts/v2/models/calibrated_model.joblib"
    )
    freeze = access.verify_training_freeze()
    assert freeze["validation_sealed"] is True


# ---------------------------------------------------------------------------
# open_validation: structural denominator guard and first-access bookkeeping.
# ---------------------------------------------------------------------------


def _write_validation_fixture(
    tmp_path, monkeypatch, n_validation_devices, n_feature_rows
):
    development_dir = tmp_path / "data/v2/development"
    development_dir.mkdir(parents=True)
    monkeypatch.setattr(access, "DEVELOPMENT_DIR", development_dir)
    monkeypatch.setattr(access, "ROOT", tmp_path)
    validation_ids = [f"validation-device-{i}" for i in range(n_validation_devices)]
    splits = pd.DataFrame(
        {"device_id": validation_ids, "split": ["validation"] * n_validation_devices}
    )
    splits.to_csv(development_dir / "device_splits.csv", index=False)
    # Distribute feature rows round-robin across validation devices so every
    # requested feature row count is reachable regardless of device count.
    feature_devices = [
        validation_ids[i % n_validation_devices] for i in range(n_feature_rows)
    ]
    pd.DataFrame({"device_id": feature_devices, "value": range(n_feature_rows)}).to_csv(
        development_dir / "events_with_features.csv", index=False
    )
    pd.DataFrame(
        {
            "device_id": feature_devices,
            "event_type": ["authorization_request"] * n_feature_rows,
        }
    ).to_csv(development_dir / "raw_events.csv", index=False)
    (tmp_path / "artifacts/v2/training").mkdir(parents=True)


def test_open_validation_fails_closed_on_wrong_structural_denominator(
    tmp_path, monkeypatch
):
    _write_validation_fixture(
        tmp_path, monkeypatch, n_validation_devices=3, n_feature_rows=10
    )
    monkeypatch.setattr(
        access,
        "verify_training_freeze",
        lambda: {"created_utc": "2026-01-01T00:00:00+00:00"},
    )
    with pytest.raises(
        RuntimeError, match="validation structural denominator mismatch"
    ):
        access.open_validation()


def test_open_validation_accepts_the_exact_frozen_boundary_and_records_first_access(
    tmp_path, monkeypatch
):
    _write_validation_fixture(
        tmp_path, monkeypatch, n_validation_devices=2_000, n_feature_rows=5_422
    )
    monkeypatch.setattr(
        access,
        "verify_training_freeze",
        lambda: {"created_utc": "2026-01-01T00:00:00+00:00"},
    )
    features, raw, first_access = access.open_validation()
    assert len(features) == 5_422
    assert len(raw) == 5_422
    assert set(features.device_id) <= {f"validation-device-{i}" for i in range(2_000)}
    access_path = tmp_path / "artifacts/v2/training/first_validation_access.json"
    assert access_path.exists()
    recorded = json.loads(access_path.read_text())
    assert (
        recorded["first_validation_access_utc"]
        == first_access["first_validation_access_utc"]
    )

    # A second call must NOT overwrite the recorded FILE -- only the first
    # access to validation is ever persisted, even though the in-memory
    # `access` dict returned each call carries a fresh "now" timestamp.
    _features_again, _raw_again, _second_access = access.open_validation()
    still_recorded = json.loads(access_path.read_text())
    assert (
        still_recorded["first_validation_access_utc"]
        == first_access["first_validation_access_utc"]
    )
