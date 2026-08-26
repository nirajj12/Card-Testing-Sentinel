import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
DEVELOPMENT_DIR = ROOT / "data/v2/development"
FREEZE_PATH = ROOT / "artifacts/v2/training/training_freeze.json"
FREEZE_DIGEST_PATH = ROOT / "artifacts/v2/training/training_freeze.sha256"

PHASE1_PROTECTED_HASHES = {
    "data/v2/development/raw_events.csv": (
        "9232c7049916cb638d7eedd3faf922b1569c38d74850df100eb98622ab73614f"
    ),
    "data/v2/development/events_with_features.csv": (
        "9fd1a9eabfa73a65362c93fa7f0595f9987bd274b324edf53b922984a076e3e4"
    ),
    "data/v2/development/device_splits.csv": (
        "c14524c2c601237e969edeb1b36edb3f67e9aabea1f875e5e1daf361181feefe"
    ),
    "data/v2/development/manifest.json": (
        "a5ec79c35de862bf50e4c69e56692e2d7feda8bcea7c01d5b3f47e68dd443693"
    ),
    "configs/v2/generation.yaml": (
        "fa57f16bd4260e5ae8917e2c101ae4e96b55ef8b69025d1c0953bb4a88da5f59"
    ),
    "configs/v2/features.yaml": (
        "64b31ae7ce33fb25f6da2fae489bdca8c461e411571be67d1b60cbab80180492"
    ),
    "configs/v2/split.yaml": (
        "8310cac885920ca2c30cfabef0a0b8d668deb8e5f8447f2723bab5f9c0ecdf87"
    ),
    "src/card_testing_sentinel/v2/features/spec.py": (
        "8773d0c82bd15354c19f51b096b11ee03e4af8bb0bb2fe87514898bb52520c4c"
    ),
    "src/card_testing_sentinel/v2/features/state.py": (
        "a18647783eb5ad63a7b91c442016e6f0e65725e4c10a4bcdc8b2dc6de6d84561"
    ),
    "src/card_testing_sentinel/v2/features/engine.py": (
        "036a275bc350784fd3b86c2c7aa07e5dc737075f37a618f44074ca95e588bf7e"
    ),
}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_phase1_protected_inputs() -> dict[str, str]:
    observed = {name: sha256_file(ROOT / name) for name in PHASE1_PROTECTED_HASHES}
    changed = {
        name: {"expected": PHASE1_PROTECTED_HASHES[name], "observed": digest}
        for name, digest in observed.items()
        if digest != PHASE1_PROTECTED_HASHES[name]
    }
    if changed:
        raise RuntimeError(f"Phase 1 protected inputs changed: {changed}")
    return observed


def verify_v1_release() -> dict[str, str]:
    entries = {}
    for line in (ROOT / "docs/v1/release_manifest.sha256").read_text().splitlines():
        if not line or line.startswith("#"):
            continue
        digest, name = line.split(maxsplit=1)
        name = name.strip().lstrip("*")
        observed = sha256_file(ROOT / name)
        if observed != digest:
            raise RuntimeError(f"V1 protected release entry changed: {name}")
        entries[name] = observed
    return entries


def _split_ids(split: str) -> set[str]:
    splits = pd.read_csv(DEVELOPMENT_DIR / "device_splits.csv")
    return set(splits.loc[splits.split.eq(split), "device_id"])


def load_training_features() -> pd.DataFrame:
    train_ids = _split_ids("train")
    frame = pd.read_csv(DEVELOPMENT_DIR / "events_with_features.csv")
    training = frame.loc[frame.device_id.isin(train_ids)].copy()
    if set(training.device_id) != train_ids or len(training) != 21_338:
        raise RuntimeError("training feature boundary failed")
    return training


def load_training_raw_events() -> pd.DataFrame:
    train_ids = _split_ids("train")
    frame = pd.read_csv(DEVELOPMENT_DIR / "raw_events.csv")
    return frame.loc[frame.device_id.isin(train_ids)].copy()


def verify_training_freeze() -> dict:
    if not FREEZE_PATH.exists() or not FREEZE_DIGEST_PATH.exists():
        raise PermissionError("validation is sealed until the training freeze exists")
    expected = FREEZE_DIGEST_PATH.read_text().strip()
    if sha256_file(FREEZE_PATH) != expected:
        raise PermissionError("training freeze hash mismatch")
    freeze = json.loads(FREEZE_PATH.read_text())
    verify_phase1_protected_inputs()
    for name, digest in freeze["phase2_frozen_artifact_hashes"].items():
        if sha256_file(ROOT / name) != digest:
            raise PermissionError(f"frozen Phase 2 artifact changed: {name}")
    if not freeze.get("validation_sealed", False):
        raise PermissionError("freeze does not attest that validation stayed sealed")
    return freeze


def open_validation() -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    freeze = verify_training_freeze()
    validation_ids = _split_ids("validation")
    features = pd.read_csv(DEVELOPMENT_DIR / "events_with_features.csv")
    raw = pd.read_csv(DEVELOPMENT_DIR / "raw_events.csv")
    features = features.loc[features.device_id.isin(validation_ids)].copy()
    raw = raw.loc[raw.device_id.isin(validation_ids)].copy()
    if len(features) != 5_422 or len(validation_ids) != 2_000:
        raise RuntimeError("validation structural denominator mismatch")
    access = {
        "first_validation_access_utc": datetime.now(UTC).isoformat(),
        "training_freeze_created_utc": freeze["created_utc"],
        "training_freeze_sha256": sha256_file(FREEZE_PATH),
    }
    access_path = ROOT / "artifacts/v2/training/first_validation_access.json"
    if not access_path.exists():
        access_path.write_text(json.dumps(access, indent=2, sort_keys=True) + "\n")
    return features, raw, access
