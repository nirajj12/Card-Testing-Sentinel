"""Immutable methodology freeze, blind generation, and one-time access guard."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import yaml

from card_testing_sentinel.common.atomic_io import atomic_write_json, atomic_write_text
from card_testing_sentinel.v2.data.generator import generate_frames
from card_testing_sentinel.v2.phase2c.amendment import verify_correction_chain
from card_testing_sentinel.v2.phase2c.confirmation import IDENTIFIER_COLUMNS
from card_testing_sentinel.v2.phase2c.resumed_evaluation import (
    verify_resumed_post_scoring,
)
from card_testing_sentinel.v2.phase3.contracts import (
    ARTIFACT_PATH,
    BLIND_SEED,
    CONFIG_PATH,
    DATA_PATH,
    DATASET_MANIFEST_PATH,
    EFFECTIVENESS_TARGETS,
    EXECUTION_AMENDMENT_SHA256,
    FREEZE_PATH,
    LEDGER_PATH,
    PHASE2C_FINAL_MANIFEST_SHA256,
    POLICY_ID,
    POLICY_SHA256,
    REPLACEMENT_FREEZE_SHA256,
    REPORT_PATH,
    RESULT_FILES,
    ROOT,
    SAFETY_ALLOWANCES,
    SCENARIO_COUNTS,
)

HISTORICAL_INPUTS = (
    "docs/v1/release_manifest.sha256",
    "docs/v2/data_contract.md",
    "docs/v2/evaluation_protocol.md",
    "docs/v2/live_serving_contract.md",
    "artifacts/v2/phase2b/training/models/selected_model.joblib",
    "artifacts/v2/phase2b/training/models/model_feature_contract.json",
    "artifacts/v2/phase2b/training/freeze/training_freeze.json",
    "artifacts/v2/phase2b/validation/final_hash_manifest.json",
    "artifacts/v2/phase2c/freeze/development_freeze_replacement_001.json",
    "artifacts/v2/phase2c/amendments/execution_amendment_001.json",
    "artifacts/v2/phase2c/confirmation/frozen_operational_policy.json",
    "artifacts/v2/phase2c/confirmation/final_hash_manifest.json",
    "artifacts/v2/phase2c/confirmation/access_ledger_completion_001.json",
    "data/v2/phase2c/confirmation_validation/manifest.json",
    "configs/v2/phase2b/requirements-lock.txt",
    "configs/v2/features.yaml",
    "src/card_testing_sentinel/v2/data/generator.py",
    "src/card_testing_sentinel/v2/features/engine.py",
    "src/card_testing_sentinel/v2/phase2b/engine.py",
    "src/card_testing_sentinel/v2/phase2b/features.py",
    "src/card_testing_sentinel/v2/phase2b/validation_policy.py",
    "src/card_testing_sentinel/v2/phase2c/policy.py",
    "src/card_testing_sentinel/v2/phase2c/replay.py",
    "src/card_testing_sentinel/v2/evaluation/metrics.py",
)
PHASE3_INPUTS = (
    "configs/v2/phase3/blind.yaml",
    "src/card_testing_sentinel/v2/phase3/__init__.py",
    "src/card_testing_sentinel/v2/phase3/contracts.py",
    "src/card_testing_sentinel/v2/phase3/lifecycle.py",
    "src/card_testing_sentinel/v2/phase3/evaluation.py",
    "scripts/v2/phase3/freeze_methodology.py",
    "scripts/v2/phase3/generate_blind.py",
    "scripts/v2/phase3/evaluate_blind.py",
    "scripts/v2/phase3/verify_blind.py",
    "tests/v2/phase3/test_lifecycle.py",
    "tests/v2/phase3/test_evaluation.py",
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def load_blind_config(root: Path = ROOT) -> dict:
    config = yaml.safe_load((root / CONFIG_PATH).read_text())
    counts = {str(key): int(value) for key, value in config["device_counts"].items()}
    if int(config["seed"]) != BLIND_SEED or counts != SCENARIO_COUNTS:
        raise PermissionError("blind seed or scenario-count contract drift")
    if float(config["validation_fraction"]) != 0.0:
        raise PermissionError("blind population must be unsplit")
    if config.get("policy_id") != POLICY_ID or config.get("evaluated_policies") != 1:
        raise PermissionError("exactly the frozen operational policy is required")
    if config.get("policy_sha256") != POLICY_SHA256:
        raise PermissionError("blind policy hash declaration drift")
    if config.get("safety_allowances") != SAFETY_ALLOWANCES:
        raise PermissionError("integer safety allowances changed")
    if config.get("effectiveness_targets") != EFFECTIVENESS_TARGETS:
        raise PermissionError("effectiveness targets changed")
    return config


def assert_real_outputs_absent(root: Path = ROOT) -> None:
    forbidden = [root / DATA_PATH, root / REPORT_PATH]
    forbidden.extend(root / ARTIFACT_PATH / name for name in RESULT_FILES)
    forbidden.extend((root / LEDGER_PATH, root / DATASET_MANIFEST_PATH))
    present = [str(path.relative_to(root)) for path in forbidden if path.exists()]
    if present:
        raise PermissionError(f"real Phase 3 data or result already exists: {present}")


def _verify_authoritative_hashes(root: Path) -> None:
    expected = {
        "artifacts/v2/phase2c/freeze/development_freeze_replacement_001.json": (
            REPLACEMENT_FREEZE_SHA256
        ),
        "artifacts/v2/phase2c/amendments/execution_amendment_001.json": (
            EXECUTION_AMENDMENT_SHA256
        ),
        "artifacts/v2/phase2c/confirmation/frozen_operational_policy.json": (
            POLICY_SHA256
        ),
        "artifacts/v2/phase2c/confirmation/final_hash_manifest.json": (
            PHASE2C_FINAL_MANIFEST_SHA256
        ),
    }
    for relative, digest in expected.items():
        path = root / relative
        if not path.is_file() or sha256_file(path) != digest:
            raise PermissionError(f"authoritative protected hash drift: {relative}")


def build_pre_access_freeze(root: Path = ROOT) -> tuple[Path, str]:
    path = root / FREEZE_PATH
    digest_path = path.with_suffix(".sha256")
    if path.exists() or digest_path.exists():
        raise FileExistsError("Phase 3 pre-access freeze already exists")
    assert_real_outputs_absent(root)
    config = load_blind_config(root)
    verify_correction_chain(root)
    verify_resumed_post_scoring(root)
    _verify_authoritative_hashes(root)
    inputs = (*HISTORICAL_INPUTS, *PHASE3_INPUTS)
    missing = [name for name in inputs if not (root / name).is_file()]
    if missing:
        raise FileNotFoundError(f"pre-access freeze inputs missing: {missing}")
    payload = {
        "version": "v2-phase3-pre-access-freeze-1",
        "created_utc": utc_now(),
        "runtime": {
            "python": sys.version.split()[0],
            "executable": sys.executable,
            "platform": platform.platform(),
        },
        "blind_seed": BLIND_SEED,
        "scenario_counts": SCENARIO_COUNTS,
        "expected_counts": {
            "devices": 2000,
            "legitimate_devices": 1700,
            "attacker_devices": 300,
        },
        "expected_policy_sha256": POLICY_SHA256,
        "expected_policy_id": POLICY_ID,
        "expected_policies_evaluated": 1,
        "safety_allowances": SAFETY_ALLOWANCES,
        "effectiveness_targets": EFFECTIVENESS_TARGETS,
        "output_paths": {
            "data": str(DATA_PATH),
            "artifacts": str(ARTIFACT_PATH),
            "report": str(REPORT_PATH),
        },
        "access_state_transitions": [
            "pre_generation",
            "post_generation_pre_scoring",
            "post_scoring",
        ],
        "final_status_names": [
            "blind_completed_passed",
            "blind_completed_failed",
            "blocked_pre_access",
            "blocked_post_generation_pre_scoring",
            "blind_execution_failed",
        ],
        "decision_semantics": {
            "scoring_moment": "pre-authorization before current outcome",
            "blocked_request": "request-side observation only; outcome suppressed",
            "later_requests": "independently feature-computed and scored",
            "ordering": "timestamp then event_sequence",
            "policy_action": "allow, review, or block for current request",
        },
        "real_blind_paths_absent_at_freeze": True,
        "protected_hashes": {name: sha256_file(root / name) for name in inputs},
        "config": json.loads(json.dumps(config, default=str)),
    }
    atomic_write_json(path, payload)
    digest = sha256_file(path)
    atomic_write_text(digest_path, digest + "\n")
    verify_pre_access_freeze(root)
    return path, digest


def verify_pre_access_freeze(root: Path = ROOT) -> dict:
    path = root / FREEZE_PATH
    digest_path = path.with_suffix(".sha256")
    if not path.is_file() or not digest_path.is_file():
        raise FileNotFoundError("Phase 3 pre-access freeze is missing")
    if sha256_file(path) != digest_path.read_text().strip():
        raise PermissionError("Phase 3 pre-access freeze digest drift")
    payload = json.loads(path.read_text())
    if (
        payload.get("blind_seed") != BLIND_SEED
        or payload.get("expected_policy_sha256") != POLICY_SHA256
        or payload.get("expected_policies_evaluated") != 1
    ):
        raise PermissionError("Phase 3 frozen methodology contract drift")
    for relative, digest in payload["protected_hashes"].items():
        path = root / relative
        if not path.is_file() or sha256_file(path) != digest:
            raise PermissionError(f"Phase 3 frozen input drift: {relative}")
    _verify_authoritative_hashes(root)
    return payload


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


def generate_blind_frames(config: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    if int(config["seed"]) != BLIND_SEED:
        raise PermissionError("blind seed must be exactly 20260828")
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


def validate_blind_frames(
    raw: pd.DataFrame,
    contract: pd.DataFrame,
    comparisons: dict[str, pd.DataFrame],
) -> dict:
    observed = contract.scenario_tag.value_counts().sort_index().to_dict()
    if observed != dict(sorted(SCENARIO_COUNTS.items())):
        raise RuntimeError("blind scenario denominators changed")
    if len(contract) != 2000 or contract.device_id.nunique() != 2000:
        raise RuntimeError("blind device denominator or identity invalid")
    if (
        int(contract.label.eq(0).sum()) != 1700
        or int(contract.label.eq(1).sum()) != 300
    ):
        raise RuntimeError("blind class denominator changed")
    requests = raw.loc[raw.event_type.eq("authorization_request")]
    outcomes = raw.loc[raw.event_type.eq("authorization_outcome")]
    completions = raw.loc[raw.event_type.eq("checkout_completion")]
    if raw.event_id.isna().any() or raw.event_id.duplicated().any():
        raise RuntimeError("blind event identity invalid")
    if requests.request_id.duplicated().any() or set(requests.request_id) != set(
        outcomes.request_id
    ):
        raise RuntimeError("blind request/outcome linkage invalid")
    request_links = requests.set_index("request_id")[["device_id", "session_id"]]
    outcome_links = outcomes.set_index("request_id")[["device_id", "session_id"]]
    if not request_links.sort_index().equals(outcome_links.sort_index()):
        raise RuntimeError("blind outcome crosses device or session")
    ordered = raw.sort_values(["timestamp", "event_sequence"], kind="mergesort")
    if list(ordered.event_id) != list(raw.event_id):
        raise RuntimeError("blind events are not globally causal")
    if raw.event_sequence.duplicated().any():
        raise RuntimeError("blind event sequence is not unique")
    current = _identifier_sets(raw)
    overlaps = {}
    for name, frame in comparisons.items():
        prior = _identifier_sets(frame)
        overlaps[name] = {
            column: len(current.get(column, set()) & prior.get(column, set()))
            for column in IDENTIFIER_COLUMNS
        }
        if any(overlaps[name].values()):
            raise RuntimeError(f"blind identifier overlap with {name}")
    return {
        "status": "passed",
        "seed": BLIND_SEED,
        "lifecycle_events": int(len(raw)),
        "authorization_requests": int(len(requests)),
        "authorization_outcomes": int(len(outcomes)),
        "checkout_completions": int(len(completions)),
        "sessions": int(raw.session_id.nunique()),
        "devices": int(contract.device_id.nunique()),
        "legitimate_devices": int(contract.label.eq(0).sum()),
        "attacker_devices": int(contract.label.eq(1).sum()),
        "scenario_counts": observed,
        "unique_event_ids": int(raw.event_id.nunique()),
        "unique_request_ids": int(requests.request_id.nunique()),
        "unique_device_ids": int(raw.device_id.nunique()),
        "ordering_violations": 0,
        "identifier_overlap_counts": overlaps,
    }


def _ledger_transition(state: str, **details) -> dict:
    return {"state": state, "recorded_utc": utc_now(), **details}


def _write_new_ledger(root: Path) -> dict:
    path = root / LEDGER_PATH
    if path.exists():
        raise FileExistsError("Phase 3 access ledger already exists")
    payload = {
        "version": "v2-phase3-access-ledger-1",
        "current_state": "pre_generation",
        "accepted_scoring_attempts": 0,
        "transitions": [_ledger_transition("pre_generation")],
        "scoring_access": [],
    }
    atomic_write_json(path, payload)
    return payload


def _append_ledger(root: Path, state: str, **details) -> dict:
    path = root / LEDGER_PATH
    payload = json.loads(path.read_text())
    allowed = {
        "pre_generation": "post_generation_pre_scoring",
        "post_generation_pre_scoring": "post_scoring",
    }
    if allowed.get(payload["current_state"]) != state:
        raise PermissionError("invalid Phase 3 access-state transition")
    payload["current_state"] = state
    payload["transitions"].append(_ledger_transition(state, **details))
    atomic_write_json(path, payload)
    return payload


def _csv(frame: pd.DataFrame) -> str:
    return frame.to_csv(index=False, lineterminator="\n", float_format="%.6f")


def write_blind_bundle(root: Path = ROOT) -> dict:
    if (root / DATA_PATH).exists():
        raise FileExistsError("blind dataset exists; regeneration refused")
    verify_pre_access_freeze(root)
    assert_real_outputs_absent(root)
    config = load_blind_config(root)
    ledger = _write_new_ledger(root)
    generation_started = time.perf_counter()
    raw, contract = generate_blind_frames(config)
    generation_seconds = time.perf_counter() - generation_started
    development = pd.read_csv(root / "data/v2/development/raw_events.csv")
    phase2b = pd.read_csv(root / "data/v2/phase2b/fresh_validation/raw_events.csv")
    phase2c = pd.read_csv(
        root / "data/v2/phase2c/confirmation_validation/raw_events.csv"
    )
    validation_started = time.perf_counter()
    structural = validate_blind_frames(
        raw,
        contract,
        {
            "development": development,
            "phase2b_fresh_validation": phase2b,
            "phase2c_confirmation": phase2c,
        },
    )
    validation_seconds = time.perf_counter() - validation_started
    output = root / DATA_PATH
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".blind-", dir=output.parent))
    try:
        raw_text = _csv(raw)
        contract_text = _csv(contract)
        atomic_write_text(staging / "raw_events.csv", raw_text)
        atomic_write_text(staging / "device_contract.csv", contract_text)
        manifest = {
            "version": config["version"],
            "created_utc": utc_now(),
            "seed": BLIND_SEED,
            "generation_count": 1,
            "accepted": True,
            "config_sha256": sha256_file(root / CONFIG_PATH),
            "pre_access_freeze_sha256": sha256_file(root / FREEZE_PATH),
            "generator_sha256": sha256_file(
                root / "src/card_testing_sentinel/v2/data/generator.py"
            ),
            "files": {
                "raw_events.csv": hashlib.sha256(raw_text.encode()).hexdigest(),
                "device_contract.csv": hashlib.sha256(
                    contract_text.encode()
                ).hexdigest(),
            },
            "structural_validation": structural,
            "determinism_evidence": {
                "fixed_seed": BLIND_SEED,
                "frozen_generator_and_config": True,
                "real_dataset_generations": 1,
                "fixture_reproduction_tested": True,
            },
            "generation_runtime": {
                "dataset_generation_seconds": generation_seconds,
                "dataset_validation_seconds": validation_seconds,
            },
        }
        atomic_write_json(staging / "manifest.json", manifest)
        os.replace(staging, output)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    atomic_write_json(root / DATASET_MANIFEST_PATH, manifest)
    manifest_digest = sha256_file(root / DATA_PATH / "manifest.json")
    if sha256_file(root / DATASET_MANIFEST_PATH) != manifest_digest:
        raise RuntimeError("artifact and dataset manifest copies differ")
    _append_ledger(
        root,
        "post_generation_pre_scoring",
        dataset_manifest_sha256=manifest_digest,
        accepted_scoring_attempts=ledger["accepted_scoring_attempts"],
    )
    verify_lifecycle(root, "post_generation_pre_scoring")
    return manifest


def verify_dataset_manifest(root: Path = ROOT) -> dict:
    data_manifest = root / DATA_PATH / "manifest.json"
    artifact_manifest = root / DATASET_MANIFEST_PATH
    if not data_manifest.is_file() or not artifact_manifest.is_file():
        raise FileNotFoundError("blind dataset manifest is missing")
    if data_manifest.read_bytes() != artifact_manifest.read_bytes():
        raise PermissionError("blind dataset manifest copies differ")
    manifest = json.loads(data_manifest.read_text())
    if (
        manifest.get("seed") != BLIND_SEED
        or manifest.get("generation_count") != 1
        or not manifest.get("accepted")
        or manifest.get("structural_validation", {}).get("status") != "passed"
    ):
        raise PermissionError("blind dataset acceptance contract invalid")
    if manifest.get("pre_access_freeze_sha256") != sha256_file(root / FREEZE_PATH):
        raise PermissionError("blind dataset is not bound to this methodology freeze")
    for name, digest in manifest["files"].items():
        path = root / DATA_PATH / name
        if not path.is_file() or sha256_file(path) != digest:
            raise PermissionError(f"blind dataset hash drift: {name}")
    return manifest


def verify_lifecycle(root: Path, state: str) -> dict:
    if state not in {
        "pre_generation",
        "post_generation_pre_scoring",
        "post_scoring",
    }:
        raise ValueError("unknown Phase 3 lifecycle state")
    verify_pre_access_freeze(root)
    data_exists = (root / DATA_PATH).exists()
    ledger_exists = (root / LEDGER_PATH).is_file()
    if state == "pre_generation":
        if data_exists or ledger_exists:
            raise PermissionError("blind data and ledger must be absent pre-generation")
        return {"state": state, "passed": True}
    if not ledger_exists:
        raise FileNotFoundError("Phase 3 access ledger is missing")
    ledger = json.loads((root / LEDGER_PATH).read_text())
    if ledger.get("current_state") != state:
        raise PermissionError("Phase 3 ledger state mismatch")
    manifest = verify_dataset_manifest(root)
    if state == "post_generation_pre_scoring":
        forbidden = [name for name in RESULT_FILES if name != "allow_all_parity.json"]
        present = [name for name in forbidden if (root / ARTIFACT_PATH / name).exists()]
        if present:
            raise PermissionError(f"policy results exist before scoring: {present}")
        if ledger.get("accepted_scoring_attempts") not in {0, 1}:
            raise PermissionError("invalid accepted scoring attempt count")
        return {"state": state, "passed": True, "ledger": ledger, "manifest": manifest}
    missing = [
        name for name in RESULT_FILES if not (root / ARTIFACT_PATH / name).is_file()
    ]
    if missing or not (root / REPORT_PATH).is_file():
        raise PermissionError(f"post-scoring outputs incomplete: {missing}")
    if ledger.get("accepted_scoring_attempts") != 1:
        raise PermissionError("post-scoring ledger must contain one accepted attempt")
    return {"state": state, "passed": True, "ledger": ledger, "manifest": manifest}


def refuse_if_scoring_accessed(root: Path = ROOT) -> None:
    path = root / LEDGER_PATH
    if not path.is_file():
        return
    ledger = json.loads(path.read_text())
    if ledger.get("accepted_scoring_attempts", 0) >= 1:
        raise PermissionError("a second blind scoring invocation is refused")


def accept_scoring_once(root: Path = ROOT) -> dict:
    refuse_if_scoring_accessed(root)
    verified = verify_lifecycle(root, "post_generation_pre_scoring")
    ledger = verified["ledger"]
    ledger["accepted_scoring_attempts"] = 1
    ledger["scoring_access"].append(
        {
            "attempt": 1,
            "accepted_utc": utc_now(),
            "policy_id": POLICY_ID,
            "policy_sha256": POLICY_SHA256,
            "dataset_manifest_sha256": sha256_file(root / DATASET_MANIFEST_PATH),
        }
    )
    atomic_write_json(root / LEDGER_PATH, ledger)
    return ledger


def complete_scoring_ledger(root: Path, status: str, output_hashes: dict) -> dict:
    path = root / LEDGER_PATH
    ledger = json.loads(path.read_text())
    if ledger.get("accepted_scoring_attempts") != 1:
        raise PermissionError("no accepted scoring access to complete")
    ledger["result_status"] = status
    ledger["output_hashes"] = output_hashes
    atomic_write_json(path, ledger)
    return _append_ledger(root, "post_scoring", result_status=status)
