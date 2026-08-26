"""One-time, seed-locked fresh-validation generation and access controls."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import yaml

from card_testing_sentinel.common.atomic_io import atomic_write_json, atomic_write_text
from card_testing_sentinel.v2.data.generator import generate_frames
from card_testing_sentinel.v2.phase2b.features import MODEL_FEATURE_COLUMNS
from card_testing_sentinel.v2.phase2b.freeze_manifest import (
    assert_absent_category,
    verify_manifest_strict,
    verify_training_freeze_file,
)

FRESH_SEED = 20260826
FRESH_RELATIVE_PATH = Path("data/v2/phase2b/fresh_validation")
EXECUTION_FREEZE_RELATIVE_PATH = Path(
    "artifacts/v2/phase2b/validation/execution_freeze.json"
)
ACCESS_LEDGER_RELATIVE_PATH = Path("artifacts/v2/phase2b/validation/access_ledger.json")
AMENDMENT_RELATIVE_PATH = Path(
    "artifacts/v2/phase2b/validation/execution_freeze_amendment_001.json"
)
TRAINING_FREEZE_SHA256 = (
    "4f6011774b7c4b43c08c401e94107aec8e8b3378b1a5ffd0b1a85cca2dea0ee8"
)
ORIGINAL_EXECUTION_FREEZE_SHA256 = (
    "a9cb60239ae599916aff0a47082e803fb6b62614fed4473749a09a2d112e0de5"
)
FRESH_MANIFEST_SHA256 = (
    "69775136c8c066ec849ed3b75a555ea0651fb0b321ce1b3fb7338c6238e1ea81"
)

PERFORMANCE_ARTIFACTS = (
    "access_ledger.json",
    "allow_all_features.csv",
    "allow_all_parity.json",
    "static_model_metrics.json",
    "calibration_reliability.csv",
    "static_threshold_metrics.csv",
    "static_scenario_subtype_metrics.csv",
    "policy_candidates.csv",
    "feasibility.json",
    "runtime.json",
    "final_hash_manifest.json",
    "final_hash_manifest.sha256",
)

IDENTIFIER_COLUMNS = (
    "event_id",
    "request_id",
    "device_id",
    "session_id",
    "card_fingerprint",
    "ip_fingerprint",
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _csv(frame: pd.DataFrame) -> str:
    return frame.to_csv(index=False, lineterminator="\n", float_format="%.6f")


def _namespace_identifiers(raw: pd.DataFrame, contract: pd.DataFrame, prefix: str):
    raw = raw.copy()
    contract = contract.copy()
    for column in IDENTIFIER_COLUMNS:
        if column in raw:
            raw[column] = raw[column].map(
                lambda value: f"{prefix}_{value}" if pd.notna(value) else value
            )
    contract["device_id"] = contract.device_id.map(lambda value: f"{prefix}_{value}")
    return raw, contract


def generate_fresh_frames(config: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Generate the frozen population and apply a seed-specific ID namespace."""
    if int(config["seed"]) != FRESH_SEED:
        raise PermissionError(f"fresh-validation seed must be exactly {FRESH_SEED}")
    if float(config["validation_fraction"]) != 0.0:
        raise ValueError("fresh validation must be one population, not a new split")
    raw, contract = generate_frames(config)
    raw, contract = _namespace_identifiers(
        raw, contract, str(config["identifier_namespace"])
    )
    contract = (
        contract.drop(columns="split").sort_values("device_id").reset_index(drop=True)
    )
    raw = raw.sort_values(
        ["timestamp", "event_sequence"], kind="mergesort"
    ).reset_index(drop=True)
    return raw, contract


def _identifier_sets(frame: pd.DataFrame) -> dict[str, set[str]]:
    return {
        name: set(frame[name].dropna().astype(str))
        for name in IDENTIFIER_COLUMNS
        if name in frame
    }


def validate_fresh_frames(
    raw: pd.DataFrame,
    contract: pd.DataFrame,
    config: dict,
    historical_raw: pd.DataFrame,
) -> dict:
    """Fail closed on structural, causal, privacy, or overlap drift."""
    expected = {str(k): int(v) for k, v in config["device_counts"].items()}
    observed = {
        str(k): int(v)
        for k, v in contract.scenario_tag.value_counts().sort_index().items()
    }
    checks: dict[str, object] = {
        "seed": int(config["seed"]),
        "scenario_counts": observed,
        "expected_scenario_counts": dict(sorted(expected.items())),
        "devices": int(contract.device_id.nunique()),
        "requests": int(raw.event_type.eq("authorization_request").sum()),
        "events": int(len(raw)),
        "sessions": int(raw.session_id.nunique()),
    }
    if observed != dict(sorted(expected.items())):
        raise RuntimeError(
            f"fresh-validation scenario denominators changed: {observed}"
        )
    if checks["devices"] != int(config["expected_counts"]["devices"]):
        raise RuntimeError("fresh-validation device denominator changed")
    if raw.event_id.isna().any() or raw.event_id.duplicated().any():
        raise RuntimeError("fresh-validation event identity is invalid")
    requests = raw.loc[raw.event_type.eq("authorization_request")]
    outcomes = raw.loc[raw.event_type.eq("authorization_outcome")]
    if requests.request_id.duplicated().any() or set(requests.request_id) != set(
        outcomes.request_id
    ):
        raise RuntimeError("fresh-validation request/outcome linkage changed")
    request_links = requests.set_index("request_id")[["device_id", "session_id"]]
    outcome_links = outcomes.set_index("request_id")[["device_id", "session_id"]]
    if not request_links.sort_index().equals(outcome_links.sort_index()):
        raise RuntimeError("fresh-validation outcome crosses device or session")
    ordered = raw.sort_values(["timestamp", "event_sequence"], kind="mergesort")
    if list(ordered.event_id) != list(raw.event_id):
        raise RuntimeError("fresh-validation events are not globally causal")
    if raw.event_sequence.duplicated().any():
        raise RuntimeError("event_sequence must be globally unique")
    for column in ("device_id", "scenario_tag", "label", "population"):
        if raw.groupby("device_id")[column].nunique(dropna=False).max() != 1:
            raise RuntimeError(f"unstable device relationship: {column}")
    if requests.groupby("card_fingerprint").card_bin.nunique().max() != 1:
        raise RuntimeError("unstable synthetic card/BIN relationship")
    generation_only_columns = {"label", "population", "attack_subtype", "scenario_tag"}
    forbidden_model_columns = generation_only_columns & set(MODEL_FEATURE_COLUMNS)
    if forbidden_model_columns:
        raise RuntimeError(
            "generated rows unexpectedly contain model features: "
            f"{forbidden_model_columns}"
        )
    current_sets = _identifier_sets(raw)
    historical_sets = _identifier_sets(historical_raw)
    overlaps = {
        name: len(current_sets.get(name, set()) & historical_sets.get(name, set()))
        for name in IDENTIFIER_COLUMNS
    }
    if any(overlaps.values()):
        raise RuntimeError(f"fresh-validation identifier overlap: {overlaps}")
    checks.update(
        {
            "identifier_overlap_counts": overlaps,
            "global_ordering": "passed",
            "request_outcome_linkage": "passed",
            "generation_columns_in_model_allowlist": [],
            "status": "passed",
        }
    )
    return checks


def write_fresh_validation_bundle(
    *,
    root: Path,
    config_path: Path,
    output_dir: Path,
    created_utc: str | None = None,
    failure_hook=None,
) -> dict:
    """Atomically accept exactly one bundle; never merge with an existing path."""
    if output_dir.resolve() != (root / FRESH_RELATIVE_PATH).resolve():
        raise PermissionError(f"fresh-validation output must be {FRESH_RELATIVE_PATH}")
    if output_dir.exists():
        raise FileExistsError(
            "fresh-validation output already exists; regeneration refused"
        )
    config = yaml.safe_load(config_path.read_text())
    if int(config["seed"]) != FRESH_SEED:
        raise PermissionError(f"fresh-validation seed must be exactly {FRESH_SEED}")
    verify_training_freeze_file(
        root / "artifacts/v2/phase2b/training/freeze/training_freeze.json",
        root / "artifacts/v2/phase2b/training/freeze/training_freeze.sha256",
        root=root,
    )
    verify_execution_freeze(root / EXECUTION_FREEZE_RELATIVE_PATH, root=root)
    raw, contract = generate_fresh_frames(config)
    historical = pd.read_csv(root / "data/v2/development/raw_events.csv")
    structural = validate_fresh_frames(raw, contract, config, historical)
    splits = pd.read_csv(root / "data/v2/development/device_splits.csv")
    current_sets = _identifier_sets(raw)
    for split_name in ("train", "validation"):
        device_ids = set(splits.loc[splits.split.eq(split_name), "device_id"])
        prior = historical.loc[historical.device_id.isin(device_ids)]
        structural[f"identifier_overlap_{split_name}"] = {
            name: len(current_sets.get(name, set()) & values)
            for name, values in _identifier_sets(prior).items()
        }
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".fresh-validation-", dir=output_dir.parent))
    try:
        raw_text = _csv(raw)
        contract_text = _csv(contract)
        atomic_write_text(staging / "raw_events.csv", raw_text)
        atomic_write_text(staging / "device_contract.csv", contract_text)
        if failure_hook is not None:
            failure_hook()
        manifest = {
            "version": config["version"],
            "seed": FRESH_SEED,
            "created_utc": created_utc or datetime.now(UTC).isoformat(),
            "config_sha256": sha256_file(config_path),
            "generator_sha256": sha256_file(Path(__file__)),
            "training_freeze_sha256": sha256_file(
                root / "artifacts/v2/phase2b/training/freeze/training_freeze.json"
            ),
            "execution_freeze_sha256": sha256_file(
                root / EXECUTION_FREEZE_RELATIVE_PATH
            ),
            "files": {
                "raw_events.csv": hashlib.sha256(raw_text.encode()).hexdigest(),
                "device_contract.csv": hashlib.sha256(
                    contract_text.encode()
                ).hexdigest(),
            },
            "structural_validation": structural,
            "accepted": True,
        }
        atomic_write_json(staging / "manifest.json", manifest)
        os.replace(staging, output_dir)
        return manifest
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def verify_dataset_manifest(
    output_dir: Path, *, expected_seed: int = FRESH_SEED
) -> dict:
    manifest_path = output_dir / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError("fresh-validation manifest is missing")
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("seed") != expected_seed or not manifest.get("accepted"):
        raise PermissionError("fresh-validation manifest seed or acceptance is invalid")
    for name, digest in manifest["files"].items():
        path = output_dir / name
        if not path.is_file() or sha256_file(path) != digest:
            raise PermissionError(f"fresh-validation dataset hash drift: {name}")
    return manifest


def write_execution_freeze(
    *,
    root: Path,
    freeze_path: Path,
    protected_paths: tuple[str, ...],
    payload: dict,
) -> tuple[Path, str]:
    if freeze_path.exists():
        raise FileExistsError("validation execution freeze already exists")
    hashes = {}
    for relative in protected_paths:
        path = root / relative
        if not path.is_file():
            raise FileNotFoundError(f"execution-freeze input missing: {relative}")
        hashes[relative] = sha256_file(path)
    manifest = {**payload, "protected_hashes": hashes}
    atomic_write_json(freeze_path, manifest)
    digest = sha256_file(freeze_path)
    atomic_write_text(freeze_path.with_suffix(".sha256"), digest + "\n")
    verify_execution_freeze(freeze_path, root=root)
    return freeze_path, digest


def verify_execution_freeze(freeze_path: Path, *, root: Path) -> dict:
    digest_path = freeze_path.with_suffix(".sha256")
    if not freeze_path.is_file() or not digest_path.is_file():
        raise FileNotFoundError("validation execution freeze or digest is missing")
    if sha256_file(freeze_path) != digest_path.read_text().strip():
        raise PermissionError("validation execution freeze digest mismatch")
    manifest = json.loads(freeze_path.read_text())
    if int(manifest.get("fresh_validation_seed", -1)) != FRESH_SEED:
        raise PermissionError("validation execution freeze has wrong seed")
    if int(manifest.get("candidate_count", -1)) != 78:
        raise PermissionError("validation execution freeze has wrong candidate count")
    for relative, digest in manifest["protected_hashes"].items():
        path = root / relative
        if not path.is_file() or sha256_file(path) != digest:
            raise PermissionError(f"validation methodology drift: {relative}")
    return manifest


def _verify_training_boundary(root: Path, *, allow_fresh_validation: bool) -> dict:
    """Verify the training freeze while authorizing only the lifecycle transition."""
    freeze_path = root / "artifacts/v2/phase2b/training/freeze/training_freeze.json"
    digest_path = root / "artifacts/v2/phase2b/training/freeze/training_freeze.sha256"
    if not freeze_path.is_file() or not digest_path.is_file():
        raise FileNotFoundError("Phase 2B training freeze or digest is missing")
    observed = sha256_file(freeze_path)
    if (
        observed != TRAINING_FREEZE_SHA256
        or digest_path.read_text().strip() != observed
    ):
        raise PermissionError("Phase 2B training freeze hash drift")
    manifest = json.loads(freeze_path.read_text())
    verify_manifest_strict(manifest, root)
    authorized = str(FRESH_RELATIVE_PATH)
    forbidden = tuple(
        name
        for name in manifest["forbidden_artifacts"]
        if not (allow_fresh_validation and name == authorized)
    )
    assert_absent_category(forbidden, root)
    return manifest


def verify_execution_amendment(root: Path) -> dict:
    """Verify the append-only correction and all unchanged original-freeze inputs."""
    original_path = root / EXECUTION_FREEZE_RELATIVE_PATH
    amendment_path = root / AMENDMENT_RELATIVE_PATH
    amendment_digest = amendment_path.with_suffix(".sha256")
    if sha256_file(original_path) != ORIGINAL_EXECUTION_FREEZE_SHA256:
        raise PermissionError("original validation execution freeze hash drift")
    if not amendment_path.is_file() or not amendment_digest.is_file():
        raise FileNotFoundError("validation execution-freeze amendment is missing")
    if sha256_file(amendment_path) != amendment_digest.read_text().strip():
        raise PermissionError("validation execution-freeze amendment hash drift")
    amendment = json.loads(amendment_path.read_text())
    if (
        amendment["original_execution_freeze_sha256"]
        != ORIGINAL_EXECUTION_FREEZE_SHA256
    ):
        raise PermissionError("amendment does not bind the original execution freeze")
    original = json.loads(original_path.read_text())
    amended_paths = set(amendment["amended_hashes"])
    for relative, digest in original["protected_hashes"].items():
        if relative not in amended_paths and sha256_file(root / relative) != digest:
            raise PermissionError(f"unrelated validation methodology drift: {relative}")
    for relative, digest in amendment["amended_hashes"].items():
        if sha256_file(root / relative) != digest:
            raise PermissionError(f"amended access-guard hash drift: {relative}")
    if (
        sha256_file(root / "artifacts/v2/phase2b/training/freeze/training_freeze.json")
        != amendment["training_freeze_sha256"]
    ):
        raise PermissionError("training freeze drift after amendment")
    return amendment


def write_execution_amendment(
    *, root: Path, created_utc: str | None = None
) -> tuple[Path, str]:
    """Append the single authorized access-guard correction; never overwrite."""
    path = root / AMENDMENT_RELATIVE_PATH
    if path.exists() or path.with_suffix(".sha256").exists():
        raise FileExistsError("validation execution-freeze amendment already exists")
    original_path = root / EXECUTION_FREEZE_RELATIVE_PATH
    if sha256_file(original_path) != ORIGINAL_EXECUTION_FREEZE_SHA256:
        raise PermissionError("original validation execution freeze hash drift")
    original = json.loads(original_path.read_text())
    amended = (
        "src/card_testing_sentinel/v2/phase2b/fresh_validation.py",
        "tests/v2/phase2b/test_fresh_validation.py",
    )
    payload = {
        "version": "v2-phase2b-validation-execution-freeze-amendment-001",
        "created_utc": created_utc or datetime.now(UTC).isoformat(),
        "reason": (
            "Replace the pre-generation-only fresh-validation absence assertion "
            "with explicit pre-generation, post-generation/pre-scoring, and "
            "post-scoring lifecycle verification. No generator, feature, model, "
            "policy, budget, selection, metric, or reporting semantics changed."
        ),
        "original_execution_freeze_sha256": ORIGINAL_EXECUTION_FREEZE_SHA256,
        "training_freeze_sha256": TRAINING_FREEZE_SHA256,
        "fresh_validation_manifest_sha256": FRESH_MANIFEST_SHA256,
        "previous_hashes": {
            name: original["protected_hashes"][name] for name in amended
        },
        "amended_hashes": {name: sha256_file(root / name) for name in amended},
        "authorized_states": [
            "pre_generation",
            "post_generation_pre_scoring",
            "post_scoring",
        ],
        "scoring_attempt_limit": 1,
        "dataset_regeneration_authorized": False,
    }
    atomic_write_json(path, payload)
    digest = sha256_file(path)
    atomic_write_text(path.with_suffix(".sha256"), digest + "\n")
    verify_execution_amendment(root)
    return path, digest


def verify_validation_lifecycle(
    *,
    root: Path,
    state: str,
    data_dir: Path | None = None,
    artifact_dir: Path | None = None,
) -> dict:
    """Fail closed across the three explicitly authorized validation states."""
    if state not in {
        "pre_generation",
        "post_generation_pre_scoring",
        "post_scoring",
    }:
        raise ValueError(f"unknown validation lifecycle state: {state}")
    data_dir = data_dir or root / FRESH_RELATIVE_PATH
    artifact_dir = artifact_dir or root / EXECUTION_FREEZE_RELATIVE_PATH.parent
    performance = {
        name: (artifact_dir / name).exists() for name in PERFORMANCE_ARTIFACTS
    }
    if state == "pre_generation":
        _verify_training_boundary(root, allow_fresh_validation=False)
        verify_execution_freeze(root / EXECUTION_FREEZE_RELATIVE_PATH, root=root)
        if data_dir.exists():
            raise PermissionError("fresh validation must be absent before generation")
        if any(performance.values()):
            raise PermissionError("scoring artifacts must be absent before generation")
        return {"state": state, "passed": True}

    training = _verify_training_boundary(root, allow_fresh_validation=True)
    amendment = verify_execution_amendment(root)
    if not data_dir.is_dir():
        raise FileNotFoundError("fresh validation must exist after generation")
    dataset = verify_dataset_manifest(data_dir)
    if sha256_file(data_dir / "manifest.json") != FRESH_MANIFEST_SHA256:
        raise PermissionError("accepted fresh-validation manifest hash drift")
    if dataset.get("seed") != FRESH_SEED:
        raise PermissionError("accepted fresh-validation seed changed")
    if dataset.get("structural_validation", {}).get("status") != "passed":
        raise PermissionError("fresh-validation structural validation did not pass")

    ledger_path = artifact_dir / "access_ledger.json"
    if state == "post_generation_pre_scoring":
        if ledger_path.exists():
            raise PermissionError("a second scoring invocation is refused")
        if any(
            value for name, value in performance.items() if name != "access_ledger.json"
        ):
            raise PermissionError(
                "performance artifacts exist without a scoring ledger"
            )
        return {
            "state": state,
            "passed": True,
            "training": training,
            "execution": amendment,
            "dataset": dataset,
        }

    missing = [name for name, exists in performance.items() if not exists]
    if missing:
        raise PermissionError(f"post-scoring artifacts are incomplete: {missing}")
    ledger = json.loads(ledger_path.read_text())
    if ledger.get("scoring_attempt") != 1 or not ledger.get("status", "").startswith(
        "completed_"
    ):
        raise PermissionError("scoring ledger is not the single accepted completion")
    feasibility = json.loads((artifact_dir / "feasibility.json").read_text())
    if feasibility["status"] == "completed_feasible":
        for name in (
            "champion_decisions.csv",
            "champion_device_summary.csv",
            "frozen_operational_policy.json",
            "frozen_operational_policy.sha256",
        ):
            if not (artifact_dir / name).is_file():
                raise PermissionError(f"feasible post-scoring artifact missing: {name}")
    return {
        "state": state,
        "passed": True,
        "training": training,
        "execution": amendment,
        "dataset": dataset,
        "ledger": ledger,
        "feasibility": feasibility,
    }


def open_fresh_validation_once(
    *, root: Path, output_dir: Path, ledger_path: Path, started_utc: str | None = None
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Verify every gate and atomically record the single scoring access."""
    if ledger_path.exists():
        raise PermissionError("a second scoring invocation is refused")
    lifecycle = verify_validation_lifecycle(
        root=root,
        state="post_generation_pre_scoring",
        data_dir=output_dir,
        artifact_dir=ledger_path.parent,
    )
    execution = lifecycle["execution"]
    dataset = verify_dataset_manifest(output_dir)
    if dataset["execution_freeze_sha256"] != sha256_file(
        root / EXECUTION_FREEZE_RELATIVE_PATH
    ):
        raise PermissionError("dataset was not generated under the frozen methodology")
    ledger = {
        "version": "v2-phase2b-fresh-validation-access-1",
        "started_utc": started_utc or datetime.now(UTC).isoformat(),
        "seed": FRESH_SEED,
        "dataset_manifest_sha256": sha256_file(output_dir / "manifest.json"),
        "execution_freeze_sha256": sha256_file(root / EXECUTION_FREEZE_RELATIVE_PATH),
        "training_freeze_sha256": execution["training_freeze_sha256"],
        "execution_freeze_amendment_sha256": sha256_file(
            root / AMENDMENT_RELATIVE_PATH
        ),
        "scoring_attempt": 1,
    }
    atomic_write_json(ledger_path, ledger)
    return (
        pd.read_csv(output_dir / "raw_events.csv"),
        pd.read_csv(output_dir / "device_contract.csv"),
        ledger,
    )


def refuse_blind_access(*_args, **_kwargs):
    raise PermissionError("blind access is not authorized in Phase 2B validation")
