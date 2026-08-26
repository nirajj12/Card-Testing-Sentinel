"""Frozen Phase 2C methodology and one-time confirmation access controls."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import yaml

from card_testing_sentinel.common.atomic_io import atomic_write_json, atomic_write_text
from card_testing_sentinel.v2.data.generator import generate_frames
from card_testing_sentinel.v2.phase2b.features import (
    MODEL_FEATURE_COLUMNS,
    MODEL_FEATURE_COLUMNS_SHA256,
)
from card_testing_sentinel.v2.phase2c.policy import (
    REASON_CODES,
    candidate_enumeration_sha256,
    enumerate_candidates,
)

ROOT = Path(__file__).resolve().parents[4]
CONFIRMATION_SEED = 20260827
CONFIRMATION_RELATIVE_PATH = Path("data/v2/phase2c/confirmation_validation")
FREEZE_RELATIVE_PATH = Path("artifacts/v2/phase2c/freeze/development_freeze.json")
EVALUATION_RELATIVE_PATH = Path("artifacts/v2/phase2c/confirmation")
TRAINING_FREEZE_SHA256 = (
    "4f6011774b7c4b43c08c401e94107aec8e8b3378b1a5ffd0b1a85cca2dea0ee8"
)
PHASE2B_EXECUTION_FREEZE_SHA256 = (
    "a9cb60239ae599916aff0a47082e803fb6b62614fed4473749a09a2d112e0de5"
)
PHASE2B_AMENDMENT_SHA256 = (
    "f79e3a3449d7d2b0c57d170d8555eb542ee4ab8f93cedfff1347522ca7d9ff19"
)
PHASE2B_POLICY_SHA256 = (
    "d57c60d5eb0f08e2d2452944e1b7db623e62de36d261506516056c42378095a3"
)
PHASE2B_FINAL_MANIFEST_SHA256 = (
    "37c9fe0520aa4998d04f9ac142b48a68af01ecc80b807f75a66fdb432b36e534"
)

IDENTIFIER_COLUMNS = (
    "event_id",
    "request_id",
    "device_id",
    "session_id",
    "card_fingerprint",
    "ip_fingerprint",
)

BASE_PERFORMANCE_ARTIFACTS = (
    "access_ledger.json",
    "allow_all_parity.json",
    "candidate_results.csv",
    "candidate_metrics.json",
    "feasibility.json",
    "runtime.json",
    "final_hash_manifest.json",
    "final_hash_manifest.sha256",
)

PROTECTED_PHASE2B = {
    "artifacts/v2/phase2b/training/freeze/training_freeze.json": (
        TRAINING_FREEZE_SHA256
    ),
    "artifacts/v2/phase2b/validation/execution_freeze.json": (
        PHASE2B_EXECUTION_FREEZE_SHA256
    ),
    "artifacts/v2/phase2b/validation/execution_freeze_amendment_001.json": (
        PHASE2B_AMENDMENT_SHA256
    ),
    "artifacts/v2/phase2b/validation/frozen_operational_policy.json": (
        PHASE2B_POLICY_SHA256
    ),
    "artifacts/v2/phase2b/validation/final_hash_manifest.json": (
        PHASE2B_FINAL_MANIFEST_SHA256
    ),
}

FREEZE_INPUTS = (
    "configs/v2/phase2c/policy.yaml",
    "configs/v2/phase2c/confirmation.yaml",
    "configs/v2/phase2c/requirements-lock.txt",
    "src/card_testing_sentinel/v2/phase2c/policy.py",
    "src/card_testing_sentinel/v2/phase2c/replay.py",
    "src/card_testing_sentinel/v2/phase2c/development.py",
    "src/card_testing_sentinel/v2/phase2c/confirmation.py",
    "src/card_testing_sentinel/v2/phase2c/evaluation.py",
    "scripts/v2/phase2c/diagnose_phase2b.py",
    "scripts/v2/phase2c/run_training_oof.py",
    "scripts/v2/phase2c/freeze_methodology.py",
    "scripts/v2/phase2c/generate_confirmation.py",
    "scripts/v2/phase2c/evaluate_confirmation.py",
    "tests/v2/phase2c/test_policy.py",
    "tests/v2/phase2c/test_replay.py",
    "tests/v2/phase2c/test_confirmation.py",
    "artifacts/v2/phase2c/development/candidate_grid.json",
    "artifacts/v2/phase2c/development/candidate_results.csv",
    "artifacts/v2/phase2c/development/candidate_metrics.json",
    "artifacts/v2/phase2c/development/fold_metrics.csv",
    "artifacts/v2/phase2c/development/fold_isolation.json",
    "artifacts/v2/phase2c/development/selection.json",
    "artifacts/v2/phase2c/development/runtime.json",
    "artifacts/v2/phase2c/diagnosis/phase2b_policy_diagnosis.json",
    "artifacts/v2/phase2c/diagnosis/score_trajectories.csv",
    "reports/v2/phase2c/phase2b_policy_diagnosis.md",
    "reports/v2/phase2c/training_oof_development.md",
)

FORBIDDEN_PATHS = (
    "data/v2/phase2c/blind",
    "artifacts/v2/phase2c/blind",
    "artifacts/v2/phase2c/phase3",
    "src/card_testing_sentinel/v2/phase2c/api.py",
    "src/card_testing_sentinel/v2/phase2c/dashboard.py",
    "artifacts/v2/phase2c/deployment",
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _csv(frame: pd.DataFrame) -> str:
    return frame.to_csv(index=False, lineterminator="\n", float_format="%.6f")


def verify_protected_phase2b(root: Path = ROOT) -> dict:
    verified = {}
    for relative, expected in PROTECTED_PHASE2B.items():
        path = root / relative
        if not path.is_file() or sha256_file(path) != expected:
            raise PermissionError(f"protected Phase 2B hash drift: {relative}")
        verified[relative] = expected
    phase2b_data = json.loads(
        (root / "data/v2/phase2b/fresh_validation/manifest.json").read_text()
    )
    if phase2b_data.get("seed") != 20260826:
        raise PermissionError("Phase 2B fresh-validation seed drift")
    for name, digest in phase2b_data["files"].items():
        path = root / "data/v2/phase2b/fresh_validation" / name
        if not path.is_file() or sha256_file(path) != digest:
            raise PermissionError(f"Phase 2B validation data drift: {name}")
    return verified


def assert_forbidden_absent(root: Path = ROOT) -> None:
    present = [name for name in FORBIDDEN_PATHS if (root / name).exists()]
    if present:
        raise PermissionError(
            f"blind/Phase 3/API/dashboard/deployment present: {present}"
        )


def build_development_freeze(root: Path = ROOT) -> tuple[Path, str]:
    """Freeze all policy, generator, validator, reports, tests, and objectives."""
    path = root / FREEZE_RELATIVE_PATH
    digest_path = path.with_suffix(".sha256")
    if path.exists() or digest_path.exists():
        raise FileExistsError("Phase 2C development freeze already exists")
    if (root / CONFIRMATION_RELATIVE_PATH).exists():
        raise PermissionError("confirmation must be absent before methodology freeze")
    if (root / EVALUATION_RELATIVE_PATH).exists():
        raise PermissionError("confirmation performance artifacts must be absent")
    assert_forbidden_absent(root)
    phase2b = verify_protected_phase2b(root)
    missing = [name for name in FREEZE_INPUTS if not (root / name).is_file()]
    if missing:
        raise FileNotFoundError(f"Phase 2C freeze inputs missing: {missing}")
    config = yaml.safe_load((root / "configs/v2/phase2c/policy.yaml").read_text())
    confirmation = yaml.safe_load(
        (root / "configs/v2/phase2c/confirmation.yaml").read_text()
    )
    candidates = enumerate_candidates(config)
    selection = json.loads(
        (root / "artifacts/v2/phase2c/development/selection.json").read_text()
    )
    if selection["candidate_enumeration_sha256"] != candidate_enumeration_sha256(
        candidates
    ):
        raise PermissionError("training selection and candidate declaration differ")
    if selection["selected_candidate"] is None:
        raise RuntimeError("no acceptable training OOF policy exists to freeze")
    if int(confirmation["seed"]) != CONFIRMATION_SEED:
        raise PermissionError("confirmation seed must be exactly 20260827")
    scenario_counts = {
        str(name): int(value) for name, value in confirmation["device_counts"].items()
    }
    expected = {
        "normal_standard": 1200,
        "normal_bad_luck": 100,
        "flash_standard": 300,
        "flash_hard_retry": 100,
        "attack_burst": 120,
        "attack_evasive": 90,
        "attack_patient": 90,
    }
    if scenario_counts != expected:
        raise PermissionError("confirmation scenario denominators changed")
    manifest = {
        "version": "v2-phase2c-development-freeze-1",
        "created_utc": datetime.now(UTC).isoformat(),
        "python_version": sys.version,
        "platform": platform.platform(),
        "confirmation_seed": CONFIRMATION_SEED,
        "confirmation_scenario_counts": scenario_counts,
        "candidate_count": len(candidates),
        "candidate_enumeration_sha256": candidate_enumeration_sha256(candidates),
        "candidates": candidates,
        "training_oof_selected_candidate": selection["selected_candidate"],
        "training_oof_selected_metrics": selection["selected_metrics"],
        "safety_rates": config["safety_rates"],
        "confirmation_integer_allowances": {
            "overall_legitimate": {"review_or_higher": 51, "block": 17},
            "normal_standard": {"review_or_higher": 24, "block": 6},
            "normal_bad_luck": {"review_or_higher": 5, "block": 2},
            "flash_standard": {"review_or_higher": 15, "block": 9},
            "flash_hard_retry": {"review_or_higher": 10, "block": 5},
        },
        "effectiveness_targets": config["effectiveness_targets"],
        "selection_order": config["selection_order"],
        "state_schema_version": config["state_schema_version"],
        "risk_semantics": {
            "accumulation": "decayed sum of calibrated request probabilities",
            "time_decay": "half-life candidate parameter applied before current score",
            "score_window": (
                "candidate high_window_hours, capped by recent_request_limit"
            ),
            "checkout_decay": "multiplicative on newly observed prior checkout count",
            "stable_retry_decay": "same-card ratio >=0.75 and amount delta <=2",
            "campaign": "raises score threshold and evidence requirement",
            "block": "repeated score or accumulated risk plus frozen corroboration",
        },
        "reason_code_contract": list(REASON_CODES),
        "model_contract": {
            "frozen_model_sha256": sha256_file(
                root / "artifacts/v2/phase2b/training/models/selected_model.joblib"
            ),
            "feature_count": len(MODEL_FEATURE_COLUMNS),
            "feature_contract_sha256": MODEL_FEATURE_COLUMNS_SHA256,
            "model_changed": False,
            "calibration_changed": False,
        },
        "protected_phase2b_hashes": phase2b,
        "protected_hashes": {name: sha256_file(root / name) for name in FREEZE_INPUTS},
        "confirmation_generated": False,
        "blind_evaluated": False,
    }
    atomic_write_json(path, manifest)
    digest = sha256_file(path)
    atomic_write_text(digest_path, digest + "\n")
    verify_development_freeze(root)
    return path, digest


def verify_development_freeze(root: Path = ROOT) -> dict:
    path = root / FREEZE_RELATIVE_PATH
    digest_path = path.with_suffix(".sha256")
    if not path.is_file() or not digest_path.is_file():
        raise FileNotFoundError("Phase 2C development freeze is missing")
    observed = sha256_file(path)
    if observed != digest_path.read_text().strip():
        raise PermissionError("Phase 2C development freeze digest drift")
    manifest = json.loads(path.read_text())
    if manifest.get("confirmation_seed") != CONFIRMATION_SEED:
        raise PermissionError("frozen confirmation seed drift")
    if manifest.get("candidate_count", 0) > 120:
        raise PermissionError("frozen candidate count exceeds limit")
    for relative, digest in manifest["protected_hashes"].items():
        path = root / relative
        if not path.is_file() or sha256_file(path) != digest:
            raise PermissionError(f"Phase 2C methodology drift: {relative}")
    verify_protected_phase2b(root)
    assert_forbidden_absent(root)
    return manifest


def _namespace_identifiers(
    raw: pd.DataFrame, contract: pd.DataFrame, prefix: str
) -> tuple[pd.DataFrame, pd.DataFrame]:
    raw = raw.copy()
    contract = contract.copy()
    for column in IDENTIFIER_COLUMNS:
        if column in raw:
            raw[column] = raw[column].map(
                lambda value: f"{prefix}_{value}" if pd.notna(value) else value
            )
    contract["device_id"] = contract.device_id.map(lambda value: f"{prefix}_{value}")
    return raw, contract


def generate_confirmation_frames(config: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    if int(config["seed"]) != CONFIRMATION_SEED:
        raise PermissionError("confirmation seed must be exactly 20260827")
    if float(config["validation_fraction"]) != 0.0:
        raise ValueError("confirmation must be one unsplit population")
    raw, contract = generate_frames(config)
    raw, contract = _namespace_identifiers(
        raw, contract, str(config["identifier_namespace"])
    )
    contract = contract.drop(columns="split").sort_values("device_id")
    raw = raw.sort_values(["timestamp", "event_sequence"], kind="mergesort")
    return raw.reset_index(drop=True), contract.reset_index(drop=True)


def _identifier_sets(frame: pd.DataFrame) -> dict[str, set[str]]:
    return {
        name: set(frame[name].dropna().astype(str))
        for name in IDENTIFIER_COLUMNS
        if name in frame
    }


def validate_confirmation_frames(
    raw: pd.DataFrame,
    contract: pd.DataFrame,
    config: dict,
    comparison_frames: dict[str, pd.DataFrame],
) -> dict:
    expected = {
        str(name): int(value) for name, value in config["device_counts"].items()
    }
    observed = {
        str(name): int(value)
        for name, value in contract.scenario_tag.value_counts().sort_index().items()
    }
    if observed != dict(sorted(expected.items())):
        raise RuntimeError("confirmation scenario denominators changed")
    if contract.device_id.nunique() != 2000:
        raise RuntimeError("confirmation device denominator changed")
    if (
        int(contract.label.eq(0).sum()) != 1700
        or int(contract.label.eq(1).sum()) != 300
    ):
        raise RuntimeError("confirmation class denominator changed")
    if raw.event_id.isna().any() or raw.event_id.duplicated().any():
        raise RuntimeError("confirmation event identity is invalid")
    requests = raw.loc[raw.event_type.eq("authorization_request")]
    outcomes = raw.loc[raw.event_type.eq("authorization_outcome")]
    if requests.request_id.duplicated().any() or set(requests.request_id) != set(
        outcomes.request_id
    ):
        raise RuntimeError("confirmation request/outcome linkage changed")
    request_links = requests.set_index("request_id")[["device_id", "session_id"]]
    outcome_links = outcomes.set_index("request_id")[["device_id", "session_id"]]
    if not request_links.sort_index().equals(outcome_links.sort_index()):
        raise RuntimeError("confirmation outcome crosses device or session")
    ordered = raw.sort_values(["timestamp", "event_sequence"], kind="mergesort")
    if list(ordered.event_id) != list(raw.event_id):
        raise RuntimeError("confirmation events are not globally causal")
    if raw.event_sequence.duplicated().any():
        raise RuntimeError("confirmation event sequence is not unique")
    current = _identifier_sets(raw)
    overlaps = {}
    for name, frame in comparison_frames.items():
        prior = _identifier_sets(frame)
        overlaps[name] = {
            column: len(current.get(column, set()) & prior.get(column, set()))
            for column in IDENTIFIER_COLUMNS
        }
        if any(overlaps[name].values()):
            raise RuntimeError(f"confirmation identifier overlap with {name}")
    return {
        "seed": int(config["seed"]),
        "scenario_counts": observed,
        "devices": int(contract.device_id.nunique()),
        "legitimate_devices": int(contract.label.eq(0).sum()),
        "attacker_devices": int(contract.label.eq(1).sum()),
        "events": int(len(raw)),
        "requests": int(requests.shape[0]),
        "sessions": int(raw.session_id.nunique()),
        "identifier_overlap_counts": overlaps,
        "global_ordering": "passed",
        "request_outcome_linkage": "passed",
        "fresh_empty_state_required": True,
        "status": "passed",
    }


def write_confirmation_bundle(root: Path = ROOT) -> dict:
    output = root / CONFIRMATION_RELATIVE_PATH
    if output.exists():
        raise FileExistsError("confirmation already exists; regeneration refused")
    verify_confirmation_lifecycle(root=root, state="pre_generation")
    freeze = verify_development_freeze(root)
    config_path = root / "configs/v2/phase2c/confirmation.yaml"
    config = yaml.safe_load(config_path.read_text())
    raw, contract = generate_confirmation_frames(config)
    development = pd.read_csv(root / "data/v2/development/raw_events.csv")
    splits = pd.read_csv(root / "data/v2/development/device_splits.csv")
    train_ids = set(splits.loc[splits.split.eq("train"), "device_id"])
    validation_ids = set(splits.loc[splits.split.eq("validation"), "device_id"])
    phase2b = pd.read_csv(root / "data/v2/phase2b/fresh_validation/raw_events.csv")
    structural = validate_confirmation_frames(
        raw,
        contract,
        config,
        {
            "training": development.loc[development.device_id.isin(train_ids)],
            "historical_validation": development.loc[
                development.device_id.isin(validation_ids)
            ],
            "phase2b_seed_20260826": phase2b,
        },
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".confirmation-", dir=output.parent))
    try:
        raw_text = _csv(raw)
        contract_text = _csv(contract)
        atomic_write_text(staging / "raw_events.csv", raw_text)
        atomic_write_text(staging / "device_contract.csv", contract_text)
        manifest = {
            "version": config["version"],
            "seed": CONFIRMATION_SEED,
            "created_utc": datetime.now(UTC).isoformat(),
            "config_sha256": sha256_file(config_path),
            "generator_sha256": sha256_file(Path(__file__)),
            "development_freeze_sha256": sha256_file(root / FREEZE_RELATIVE_PATH),
            "candidate_enumeration_sha256": freeze["candidate_enumeration_sha256"],
            "files": {
                "raw_events.csv": hashlib.sha256(raw_text.encode()).hexdigest(),
                "device_contract.csv": hashlib.sha256(
                    contract_text.encode()
                ).hexdigest(),
            },
            "structural_validation": structural,
            "accepted": True,
            "generation_count": 1,
        }
        atomic_write_json(staging / "manifest.json", manifest)
        os.replace(staging, output)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    verify_confirmation_lifecycle(root=root, state="post_generation_pre_scoring")
    return manifest


def verify_dataset_manifest(data_dir: Path) -> dict:
    path = data_dir / "manifest.json"
    if not path.is_file():
        raise FileNotFoundError("confirmation manifest is missing")
    manifest = json.loads(path.read_text())
    if (
        manifest.get("seed") != CONFIRMATION_SEED
        or not manifest.get("accepted")
        or manifest.get("generation_count") != 1
    ):
        raise PermissionError("confirmation seed/acceptance/generation count invalid")
    for name, digest in manifest["files"].items():
        file_path = data_dir / name
        if not file_path.is_file() or sha256_file(file_path) != digest:
            raise PermissionError(f"confirmation dataset hash drift: {name}")
    if manifest.get("structural_validation", {}).get("status") != "passed":
        raise PermissionError("confirmation structural validation did not pass")
    return manifest


def verify_one_time_state(
    *, data_dir: Path, artifact_dir: Path, state: str, expected_seed: int
) -> dict:
    """Pure lifecycle guard used by real paths and temporary-fixture tests."""
    if state not in {
        "pre_generation",
        "post_generation_pre_scoring",
        "post_scoring",
    }:
        raise ValueError("unknown confirmation lifecycle state")
    performance = {
        name: (artifact_dir / name).exists() for name in BASE_PERFORMANCE_ARTIFACTS
    }
    if state == "pre_generation":
        if data_dir.exists():
            raise PermissionError("confirmation must be absent before generation")
        if any(performance.values()):
            raise PermissionError("scoring artifacts must be absent before generation")
        return {"state": state, "passed": True}
    manifest_path = data_dir / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError("confirmation must exist after generation")
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("seed") != expected_seed or not manifest.get("accepted"):
        raise PermissionError("confirmation seed or acceptance is invalid")
    for name, digest in manifest.get("files", {}).items():
        path = data_dir / name
        if not path.is_file() or sha256_file(path) != digest:
            raise PermissionError(f"confirmation data drift: {name}")
    if manifest.get("structural_validation", {}).get("status") != "passed":
        raise PermissionError("confirmation structure did not pass")
    ledger = artifact_dir / "access_ledger.json"
    if state == "post_generation_pre_scoring":
        if ledger.exists():
            raise PermissionError("a second confirmation evaluation is refused")
        if any(
            exists
            for name, exists in performance.items()
            if name != "access_ledger.json"
        ):
            raise PermissionError("performance artifacts exist without a ledger")
        return {"state": state, "passed": True, "manifest": manifest}
    missing = [name for name, exists in performance.items() if not exists]
    if missing:
        raise PermissionError(f"post-scoring artifacts incomplete: {missing}")
    ledger_payload = json.loads(ledger.read_text())
    if ledger_payload.get("scoring_attempt") != 1 or not str(
        ledger_payload.get("status", "")
    ).startswith("completed_"):
        raise PermissionError("ledger is not one accepted completed evaluation")
    feasibility = json.loads((artifact_dir / "feasibility.json").read_text())
    if feasibility["status"] == "completed_feasible":
        required = (
            "champion_decisions.csv",
            "champion_device_summary.csv",
            "frozen_operational_policy.json",
            "frozen_operational_policy.sha256",
            "phase2b_vs_phase2c.json",
        )
        missing_feasible = [
            name for name in required if not (artifact_dir / name).is_file()
        ]
        if missing_feasible:
            raise PermissionError(
                f"feasible confirmation artifacts incomplete: {missing_feasible}"
            )
    return {
        "state": state,
        "passed": True,
        "manifest": manifest,
        "ledger": ledger_payload,
        "feasibility": feasibility,
    }


def verify_confirmation_lifecycle(*, root: Path = ROOT, state: str) -> dict:
    freeze = verify_development_freeze(root)
    result = verify_one_time_state(
        data_dir=root / CONFIRMATION_RELATIVE_PATH,
        artifact_dir=root / EVALUATION_RELATIVE_PATH,
        state=state,
        expected_seed=CONFIRMATION_SEED,
    )
    if state != "pre_generation":
        manifest = verify_dataset_manifest(root / CONFIRMATION_RELATIVE_PATH)
        if manifest["development_freeze_sha256"] != sha256_file(
            root / FREEZE_RELATIVE_PATH
        ):
            raise PermissionError("confirmation was not generated under this freeze")
        if (
            manifest["candidate_enumeration_sha256"]
            != freeze["candidate_enumeration_sha256"]
        ):
            raise PermissionError("confirmation candidate declaration drift")
    return result


def open_confirmation_once(
    root: Path = ROOT,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    artifact_dir = root / EVALUATION_RELATIVE_PATH
    ledger_path = artifact_dir / "access_ledger.json"
    if ledger_path.exists():
        raise PermissionError("a second confirmation evaluation is refused")
    verify_confirmation_lifecycle(root=root, state="post_generation_pre_scoring")
    manifest = verify_dataset_manifest(root / CONFIRMATION_RELATIVE_PATH)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    ledger = {
        "version": "v2-phase2c-confirmation-access-1",
        "started_utc": datetime.now(UTC).isoformat(),
        "seed": CONFIRMATION_SEED,
        "dataset_manifest_sha256": sha256_file(
            root / CONFIRMATION_RELATIVE_PATH / "manifest.json"
        ),
        "development_freeze_sha256": sha256_file(root / FREEZE_RELATIVE_PATH),
        "candidate_enumeration_sha256": manifest["candidate_enumeration_sha256"],
        "scoring_attempt": 1,
        "status": "started",
    }
    atomic_write_json(ledger_path, ledger)
    return (
        pd.read_csv(root / CONFIRMATION_RELATIVE_PATH / "raw_events.csv"),
        pd.read_csv(root / CONFIRMATION_RELATIVE_PATH / "device_contract.csv"),
        ledger,
    )


def refuse_blind_access(*_args, **_kwargs):
    raise PermissionError("blind access is not authorized in Phase 2C")
