"""Append-only correction chain for Phase 2C replay and confirmation resume."""

from __future__ import annotations

import json
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import scipy
import sklearn
import yaml

from card_testing_sentinel.common.atomic_io import atomic_write_json, atomic_write_text
from card_testing_sentinel.v2.phase2b.validation_policy import OptimizedFrozenScorer
from card_testing_sentinel.v2.phase2c.confirmation import (
    CONFIRMATION_RELATIVE_PATH,
    EVALUATION_RELATIVE_PATH,
    PROTECTED_PHASE2B,
    ROOT,
    sha256_file,
)

ORIGINAL_FREEZE_SHA256 = (
    "e3220ae35015ed5bf9737e4a6293cb11fc2351ab2aae6fee352ac8db1506bc54"
)
CONFIRMATION_MANIFEST_SHA256 = (
    "55aeef4ed02e4d22b15a420567db69459fb247ba23e59b099b85243017d7ab3f"
)
CONFIRMATION_RAW_SHA256 = (
    "98a9d99fcd35f828b0eedafe727d0ead8ad71ce7b1b6b0fd3dcbb2940eb17d26"
)
CONFIRMATION_CONTRACT_SHA256 = (
    "834624d0b9b97357547022eefcf1d6014339f52d618bfca1625bcaedbdd6b5d8"
)
ORIGINAL_LEDGER_SHA256 = (
    "40dc6cf9013f6de3818f936b83918aa5c20b6ccbfbcf08d3731438f16b26c3ae"
)
CANONICAL_PYTHON = "/Users/nirajmac/envs/card-testing-sentinel-v2b/bin/python"

AMENDMENT_DIR = Path("artifacts/v2/phase2c/amendments")
INVALIDATION_PATH = Path(
    "artifacts/v2/phase2c/freeze/development_freeze_invalidation_001.json"
)
REPLACEMENT_FREEZE_PATH = Path(
    "artifacts/v2/phase2c/freeze/development_freeze_replacement_001.json"
)
EXECUTION_AMENDMENT_PATH = AMENDMENT_DIR / "execution_amendment_001.json"
REPRODUCTION_EVIDENCE_PATH = AMENDMENT_DIR / "canonical_reproduction_001.json"
LEDGER_AMENDMENT_PATH = EVALUATION_RELATIVE_PATH / "access_ledger_amendment_001.json"
LEDGER_COMPLETION_PATH = EVALUATION_RELATIVE_PATH / "access_ledger_completion_001.json"
CORRECTED_DEVELOPMENT = Path("artifacts/v2/phase2c/development_causal_replay_001")

EXPECTED_RUNTIME = {
    "python": "3.11.15",
    "scikit_learn": "1.6.1",
    "numpy": "1.26.4",
    "pandas": "2.2.3",
    "scipy": "1.14.1",
    "joblib": "1.4.2",
}

CORRECTED_FREEZE_INPUTS = (
    "configs/v2/phase2c/policy.yaml",
    "configs/v2/phase2c/confirmation.yaml",
    "configs/v2/phase2c/requirements-lock.txt",
    "src/card_testing_sentinel/v2/phase2c/policy.py",
    "src/card_testing_sentinel/v2/phase2c/replay.py",
    "src/card_testing_sentinel/v2/phase2c/development.py",
    "src/card_testing_sentinel/v2/phase2c/confirmation.py",
    "src/card_testing_sentinel/v2/phase2c/evaluation.py",
    "src/card_testing_sentinel/v2/phase2c/amendment.py",
    "src/card_testing_sentinel/v2/phase2c/resumed_evaluation.py",
    "scripts/v2/phase2c/run_training_oof.py",
    "scripts/v2/phase2c/create_replay_correction.py",
    "scripts/v2/phase2c/resume_confirmation.py",
    "tests/v2/phase2c/test_policy.py",
    "tests/v2/phase2c/test_replay.py",
    "tests/v2/phase2c/test_confirmation.py",
    "tests/v2/phase2c/test_resume.py",
    "artifacts/v2/phase2c/development_causal_replay_001/candidate_grid.json",
    "artifacts/v2/phase2c/development_causal_replay_001/candidate_results.csv",
    "artifacts/v2/phase2c/development_causal_replay_001/candidate_metrics.json",
    "artifacts/v2/phase2c/development_causal_replay_001/fold_metrics.csv",
    "artifacts/v2/phase2c/development_causal_replay_001/fold_isolation.json",
    "artifacts/v2/phase2c/development_causal_replay_001/selection.json",
    "artifacts/v2/phase2c/development_causal_replay_001/runtime.json",
    "artifacts/v2/phase2c/development_causal_replay_001/selected_oof_decisions.csv",
    "artifacts/v2/phase2c/development_causal_replay_001/selected_oof_device_summary.csv",
    "reports/v2/phase2c/training_oof_development_causal_replay_001.md",
)

FORBIDDEN = (
    "data/v2/phase2c/blind",
    "artifacts/v2/phase2c/blind",
    "artifacts/v2/phase2c/phase3",
    "src/card_testing_sentinel/v2/phase2c/api.py",
    "src/card_testing_sentinel/v2/phase2c/dashboard.py",
    "artifacts/v2/phase2c/deployment",
)


def canonical_runtime() -> dict:
    observed = {
        "python": platform.python_version(),
        "scikit_learn": sklearn.__version__,
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "scipy": scipy.__version__,
        "joblib": joblib.__version__,
        "executable": sys.executable,
    }
    if observed["executable"] != CANONICAL_PYTHON:
        raise PermissionError("Phase 2C correction requires the canonical Python")
    for name, expected in EXPECTED_RUNTIME.items():
        if observed[name] != expected:
            raise PermissionError(
                f"canonical runtime drift for {name}: {observed[name]} != {expected}"
            )
    return observed


def verify_preserved_evidence(root: Path = ROOT) -> dict:
    expected = {
        "artifacts/v2/phase2c/freeze/development_freeze.json": (ORIGINAL_FREEZE_SHA256),
        str(CONFIRMATION_RELATIVE_PATH / "manifest.json"): (
            CONFIRMATION_MANIFEST_SHA256
        ),
        str(CONFIRMATION_RELATIVE_PATH / "raw_events.csv"): CONFIRMATION_RAW_SHA256,
        str(CONFIRMATION_RELATIVE_PATH / "device_contract.csv"): (
            CONFIRMATION_CONTRACT_SHA256
        ),
        str(EVALUATION_RELATIVE_PATH / "access_ledger.json"): (ORIGINAL_LEDGER_SHA256),
        **PROTECTED_PHASE2B,
    }
    for relative, digest in expected.items():
        path = root / relative
        if not path.is_file() or sha256_file(path) != digest:
            raise PermissionError(f"preserved evidence drift: {relative}")
    ledger = json.loads(
        (root / EVALUATION_RELATIVE_PATH / "access_ledger.json").read_text()
    )
    if ledger.get("scoring_attempt") != 1 or ledger.get("status") != "started":
        raise PermissionError("original confirmation ledger is not untouched attempt 1")
    present = [relative for relative in FORBIDDEN if (root / relative).exists()]
    if present:
        raise PermissionError(f"forbidden Phase 2C paths exist: {present}")
    return expected


def _assert_no_performance_outputs(root: Path) -> None:
    allowed = {
        "access_ledger.json",
        "access_ledger_amendment_001.json",
        "access_ledger_amendment_001.sha256",
    }
    output = root / EVALUATION_RELATIVE_PATH
    unexpected = [
        path.name
        for path in output.iterdir()
        if path.is_file() and path.name not in allowed
    ]
    if unexpected:
        raise PermissionError(
            f"confirmation performance outputs already exist: {unexpected}"
        )


def _model_parity(root: Path) -> dict:
    artifact = joblib.load(
        root / "artifacts/v2/phase2b/training/models/selected_model.joblib"
    )
    frame = pd.read_csv(
        root / "artifacts/v2/phase2b/training/models/serialization_fixture.csv"
    ).head(128)
    scorer = OptimizedFrozenScorer(artifact)
    optimized = scorer.verify_parity(frame, 1e-12)
    expected = np.asarray(
        json.loads(
            (
                root / "artifacts/v2/phase2b/training/models/"
                "serialization_subprocess_predictions.json"
            ).read_text()
        ),
        dtype=float,
    )
    observed = artifact.predict_proba(frame)
    serialized_difference = float(np.max(np.abs(observed - expected), initial=0.0))
    if serialized_difference > 1e-12:
        raise PermissionError("canonical serialized-model probability parity failed")
    return {
        "rows": 128,
        "optimized_raw_and_calibrated": optimized,
        "serialized_calibrated_maximum_absolute_difference": serialized_difference,
        "tolerance": 1e-12,
        "passed": True,
    }


def _corrected_development_evidence(root: Path) -> dict:
    selection = json.loads(
        (root / CORRECTED_DEVELOPMENT / "selection.json").read_text()
    )
    grid = json.loads(
        (root / CORRECTED_DEVELOPMENT / "candidate_grid.json").read_text()
    )
    isolation = json.loads(
        (root / CORRECTED_DEVELOPMENT / "fold_isolation.json").read_text()
    )
    decisions = pd.read_csv(root / CORRECTED_DEVELOPMENT / "selected_oof_decisions.csv")
    expected_requests = 21338
    checks = {
        "candidate_count": selection["candidate_count"],
        "candidate_enumeration_sha256": selection["candidate_enumeration_sha256"],
        "candidate_parameters_match_grid": (
            selection["candidate_enumeration_sha256"] == grid["enumeration_sha256"]
        ),
        "selected_candidate": selection["selected_candidate"],
        "selected_metrics": selection["selected_metrics"],
        "selected_stability": selection["selected_stability"],
        "acceptable_candidate_count": selection["acceptable_candidate_count"],
        "zero_device_overlap": isolation["all_pairwise_device_overlaps"],
        "raw_authorization_requests": expected_requests,
        "decision_rows": int(len(decisions)),
        "unique_decision_events": int(decisions.event_id.nunique()),
        "missing_raw_probabilities": int(decisions.raw_probability.isna().sum()),
        "missing_calibrated_probabilities": int(
            decisions.calibrated_probability.isna().sum()
        ),
        "counterfactual_after_block_rows": int(
            decisions.action.eq("counterfactual_after_block").sum()
        ),
        "action_counts": decisions.action.value_counts().sort_index().to_dict(),
    }
    if (
        checks["candidate_count"] != 20
        or checks["selected_candidate"]["candidate_id"] != "phase2c_003"
        or not checks["candidate_parameters_match_grid"]
        or checks["zero_device_overlap"] != 0
        or checks["decision_rows"] != expected_requests
        or checks["unique_decision_events"] != expected_requests
        or checks["missing_raw_probabilities"]
        or checks["missing_calibrated_probabilities"]
        or checks["counterfactual_after_block_rows"]
    ):
        raise PermissionError("corrected causal OOF development evidence is incomplete")
    return checks


def _write_hashed(path: Path, payload: dict) -> str:
    atomic_write_json(path, payload)
    digest = sha256_file(path)
    atomic_write_text(path.with_suffix(".sha256"), digest + "\n")
    return digest


def create_correction_chain(root: Path = ROOT) -> dict:
    runtime = canonical_runtime()
    preserved = verify_preserved_evidence(root)
    _assert_no_performance_outputs(root)
    paths = (
        REPRODUCTION_EVIDENCE_PATH,
        INVALIDATION_PATH,
        REPLACEMENT_FREEZE_PATH,
        EXECUTION_AMENDMENT_PATH,
        LEDGER_AMENDMENT_PATH,
    )
    if any(
        (root / path).exists() or (root / path).with_suffix(".sha256").exists()
        for path in paths
    ):
        raise FileExistsError("Phase 2C correction chain already exists")
    missing = [
        relative
        for relative in CORRECTED_FREEZE_INPUTS
        if not (root / relative).is_file()
    ]
    if missing:
        raise FileNotFoundError(f"corrected freeze inputs missing: {missing}")
    model_parity = _model_parity(root)
    development = _corrected_development_evidence(root)
    created = datetime.now(UTC).isoformat()
    evidence = {
        "version": "v2-phase2c-canonical-reproduction-001",
        "created_utc": created,
        "runtime": runtime,
        "model_parity": model_parity,
        "development": development,
        "causal_replay": {
            "current_request_block_only": True,
            "blocked_request_observed_in_request_side_state": True,
            "blocked_outcome_suppressed": True,
            "dependent_checkout_suppressed": True,
            "later_requests_feature_computed_and_scored": True,
            "per_fold_model_and_calibrator_used": True,
            "every_raw_request_has_one_decision": True,
        },
        "confirmation_accessed_for_reproduction": False,
    }
    evidence_digest = _write_hashed(root / REPRODUCTION_EVIDENCE_PATH, evidence)
    invalidation = {
        "version": "v2-phase2c-development-freeze-invalidation-001",
        "created_utc": created,
        "invalidated_freeze_sha256": ORIGINAL_FREEZE_SHA256,
        "reason": (
            "Original replay treated a current-request block as a permanent-device "
            "block and skipped later scoring. The confirmation dataset was generated "
            "but zero candidates were scored."
        ),
        "confirmation_manifest_sha256": CONFIRMATION_MANIFEST_SHA256,
        "confirmation_data_modified": False,
        "performance_results_seen": False,
        "candidates_scored": 0,
        "blind_evaluated": False,
    }
    invalidation_digest = _write_hashed(root / INVALIDATION_PATH, invalidation)
    config = yaml.safe_load((root / "configs/v2/phase2c/policy.yaml").read_text())
    replacement = {
        "version": "v2-phase2c-development-freeze-replacement-001",
        "created_utc": created,
        "replaces_freeze_sha256": ORIGINAL_FREEZE_SHA256,
        "invalidation_sha256": invalidation_digest,
        "canonical_reproduction_sha256": evidence_digest,
        "confirmation_seed": 20260827,
        "confirmation_manifest_sha256": CONFIRMATION_MANIFEST_SHA256,
        "confirmation_raw_sha256": CONFIRMATION_RAW_SHA256,
        "confirmation_device_contract_sha256": CONFIRMATION_CONTRACT_SHA256,
        "confirmation_generated_before_replacement": True,
        "confirmation_candidates_scored_before_replacement": 0,
        "candidate_count": development["candidate_count"],
        "candidate_enumeration_sha256": development["candidate_enumeration_sha256"],
        "candidates": json.loads(
            (root / CORRECTED_DEVELOPMENT / "candidate_grid.json").read_text()
        )["candidates"],
        "training_oof_selected_candidate": development["selected_candidate"],
        "training_oof_selected_metrics": development["selected_metrics"],
        "training_oof_selected_stability": development["selected_stability"],
        "safety_rates": config["safety_rates"],
        "effectiveness_targets": config["effectiveness_targets"],
        "selection_order": config["selection_order"],
        "policy_or_threshold_changes": False,
        "replay_semantic_change_only": True,
        "protected_phase2b_hashes": {
            relative: digest
            for relative, digest in preserved.items()
            if relative in PROTECTED_PHASE2B
        },
        "protected_hashes": {
            relative: sha256_file(root / relative)
            for relative in CORRECTED_FREEZE_INPUTS
        },
        "blind_evaluated": False,
    }
    replacement_digest = _write_hashed(root / REPLACEMENT_FREEZE_PATH, replacement)
    execution = {
        "version": "v2-phase2c-execution-amendment-001",
        "created_utc": created,
        "original_freeze_sha256": ORIGINAL_FREEZE_SHA256,
        "effective_replacement_freeze_sha256": replacement_digest,
        "incorrect_runtime": {"scikit_learn": "1.9.0"},
        "correct_runtime": runtime,
        "failure": {
            "exception": "AttributeError: Can't get attribute '_RemainderColsList'",
            "stage": "frozen model load before scoring",
            "requests_scored": 0,
            "candidates_scored": 0,
            "metrics_created": False,
        },
        "canonical_reproduction_sha256": evidence_digest,
        "confirmation_hashes": {
            "manifest": CONFIRMATION_MANIFEST_SHA256,
            "raw_events": CONFIRMATION_RAW_SHA256,
            "device_contract": CONFIRMATION_CONTRACT_SHA256,
        },
        "policy_budget_threshold_target_candidate_changes": False,
        "confirmation_regeneration_authorized": False,
        "resume_same_logical_attempt_authorized": True,
    }
    execution_digest = _write_hashed(root / EXECUTION_AMENDMENT_PATH, execution)
    ledger_amendment = {
        "version": "v2-phase2c-access-ledger-amendment-001",
        "created_utc": created,
        "original_access_ledger_sha256": ORIGINAL_LEDGER_SHA256,
        "scoring_attempt": 1,
        "attempt_1_failure": {
            "failed_before_scoring": True,
            "reason": "incompatible scikit-learn runtime",
            "requests_scored": 0,
            "candidates_scored": 0,
            "metrics_created": False,
        },
        "execution_amendment_sha256": execution_digest,
        "effective_replacement_freeze_sha256": replacement_digest,
        "resume_same_logical_attempt_authorized": True,
        "second_independent_evaluation_authorized": False,
    }
    ledger_digest = _write_hashed(root / LEDGER_AMENDMENT_PATH, ledger_amendment)
    verify_correction_chain(root)
    return {
        "invalidation_sha256": invalidation_digest,
        "replacement_freeze_sha256": replacement_digest,
        "execution_amendment_sha256": execution_digest,
        "ledger_amendment_sha256": ledger_digest,
        "canonical_reproduction_sha256": evidence_digest,
    }


def _verify_hashed(path: Path) -> tuple[dict, str]:
    digest_path = path.with_suffix(".sha256")
    if not path.is_file() or not digest_path.is_file():
        raise FileNotFoundError(f"append-only correction record missing: {path}")
    digest = sha256_file(path)
    if digest != digest_path.read_text().strip():
        raise PermissionError(f"append-only correction record drift: {path}")
    return json.loads(path.read_text()), digest


def verify_correction_chain(root: Path = ROOT) -> dict:
    canonical_runtime()
    verify_preserved_evidence(root)
    evidence, evidence_digest = _verify_hashed(root / REPRODUCTION_EVIDENCE_PATH)
    invalidation, invalidation_digest = _verify_hashed(root / INVALIDATION_PATH)
    replacement, replacement_digest = _verify_hashed(root / REPLACEMENT_FREEZE_PATH)
    execution, execution_digest = _verify_hashed(root / EXECUTION_AMENDMENT_PATH)
    ledger, ledger_digest = _verify_hashed(root / LEDGER_AMENDMENT_PATH)
    if (
        invalidation["invalidated_freeze_sha256"] != ORIGINAL_FREEZE_SHA256
        or replacement["invalidation_sha256"] != invalidation_digest
        or replacement["canonical_reproduction_sha256"] != evidence_digest
        or execution["effective_replacement_freeze_sha256"] != replacement_digest
        or execution["canonical_reproduction_sha256"] != evidence_digest
        or ledger["execution_amendment_sha256"] != execution_digest
        or ledger["effective_replacement_freeze_sha256"] != replacement_digest
        or not ledger["resume_same_logical_attempt_authorized"]
    ):
        raise PermissionError("Phase 2C correction-chain binding failed")
    for relative, digest in replacement["protected_hashes"].items():
        path = root / relative
        if not path.is_file() or sha256_file(path) != digest:
            raise PermissionError(f"corrected methodology drift: {relative}")
    if evidence["development"]["candidate_count"] != 20:
        raise PermissionError("corrected development candidate count drift")
    return {
        "invalidation": invalidation,
        "invalidation_sha256": invalidation_digest,
        "replacement": replacement,
        "replacement_freeze_sha256": replacement_digest,
        "execution": execution,
        "execution_amendment_sha256": execution_digest,
        "ledger_amendment": ledger,
        "ledger_amendment_sha256": ledger_digest,
        "evidence": evidence,
        "evidence_sha256": evidence_digest,
    }


def refuse_if_already_resumed(root: Path = ROOT) -> None:
    if (root / LEDGER_COMPLETION_PATH).exists():
        raise PermissionError("a second confirmation evaluation is refused")
