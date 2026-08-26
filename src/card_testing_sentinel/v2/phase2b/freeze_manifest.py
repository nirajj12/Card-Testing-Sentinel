"""Phase 2B freeze-manifest builder (Gate F).

This module implements a reusable mechanism for building and verifying a
future Phase 2B freeze manifest. It is deliberately NOT invoked anywhere in
this phase to create a real freeze -- freezing a Phase 2B model or policy is
out of scope until a Phase 2B candidate has actually been trained and
selected under an approved development process. Its correctness (including
fail-closed behavior on missing or changed files, and the guard against a
premature fresh-validation/blind read) is proven by
``tests/v2/phase2b/test_gate_f_freeze_manifest.py`` using synthetic
temporary-directory fixtures only -- it is never pointed at real blind data.

Category model
--------------
A Phase 2B freeze manifest hashes five kinds of *already-existing* material
(fail closed if any required file is missing or its hash has drifted since
the caller's recorded value), and separately *guards* two kinds of material
that must not exist yet at manifest-build time:

* ``historical_phase2``      -- the frozen, immutable Phase 2 evidence chain
                                  (must exist, verified against ``training_freeze.json``
                                  and the Phase-2 closeout artifacts; never regenerated
                                  here).
* ``source_code``             -- generator/data-contract/feature/model/policy/
                                  evaluation source modules that determine what a
                                  Phase 2B run would do.
* ``config``                  -- every YAML config governing generation, features,
                                  split, training, and policy.
* ``development_data_manifest`` -- the development dataset's own manifest/split
                                  files (not the raw event rows themselves).
* ``phase2b_development``     -- the caller-supplied list of this run's own new
                                  OOF predictions / training metrics / serialized
                                  model & calibration artifacts / candidate-grid
                                  derivation / budgets-objective-tie-break spec /
                                  first-fresh-validation-access ledger, wherever the
                                  caller has actually written them under
                                  ``artifacts/v2/phase2b/`` or ``reports/v2/phase2b/``.
* ``fresh_validation``        -- MUST NOT exist yet; asserted absent, never hashed.
* ``blind``                   -- MUST NOT exist yet; asserted absent, never hashed.
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path

from card_testing_sentinel.common.atomic_io import atomic_write_json, atomic_write_text

ROOT = Path(__file__).resolve().parents[4]

HISTORICAL_CATEGORY = "historical_phase2"
SOURCE_CATEGORY = "source_code"
CONFIG_CATEGORY = "config"
DEV_DATA_CATEGORY = "development_data_manifest"
PHASE2B_DEVELOPMENT_CATEGORY = "phase2b_development"
FRESH_VALIDATION_CATEGORY = "fresh_validation"
BLIND_CATEGORY = "blind"

# The immutable Phase 2 evidence chain. These are never rewritten by this
# module; they are only read and hash-verified.
HISTORICAL_PHASE2_INPUTS: tuple[str, ...] = (
    "artifacts/v2/training/training_freeze.json",
    "artifacts/v2/training/training_freeze.sha256",
    "artifacts/v2/phase2_closeout_manifest.sha256",
    "artifacts/v2/validation_execution_amendment_001.json",
    "artifacts/v2/metrics/validation_policy_candidates.csv",
    "artifacts/v2/metrics/validation_blocked_metrics.json",
    "reports/v2/modeling/phase2_final_closeout.md",
)

# Source code that determines what any Phase 2B training/evaluation run does.
SOURCE_CODE_INPUTS: tuple[str, ...] = (
    "src/card_testing_sentinel/v2/data/generator.py",
    "src/card_testing_sentinel/v2/data/contracts.py",
    "src/card_testing_sentinel/v2/data/validation.py",
    "src/card_testing_sentinel/v2/features/spec.py",
    "src/card_testing_sentinel/v2/features/state.py",
    "src/card_testing_sentinel/v2/features/engine.py",
    "src/card_testing_sentinel/v2/features/batch.py",
    "src/card_testing_sentinel/v2/modeling/features.py",
    "src/card_testing_sentinel/v2/modeling/folds.py",
    "src/card_testing_sentinel/v2/modeling/candidates.py",
    "src/card_testing_sentinel/v2/modeling/weights.py",
    "src/card_testing_sentinel/v2/modeling/training.py",
    "src/card_testing_sentinel/v2/modeling/artifacts.py",
    "src/card_testing_sentinel/v2/evaluation/calibration.py",
    "src/card_testing_sentinel/v2/evaluation/metrics.py",
    "src/card_testing_sentinel/v2/evaluation/eda.py",
    "src/card_testing_sentinel/v2/evaluation/sequential.py",
    "src/card_testing_sentinel/v2/evaluation/access.py",
    "src/card_testing_sentinel/v2/policy/rules.py",
    "src/card_testing_sentinel/v2/policy/selection.py",
    "src/card_testing_sentinel/v2/policy/engine.py",
    "src/card_testing_sentinel/v2/policy/blocked.py",
    "src/card_testing_sentinel/v2/policy/evaluation.py",
)

CONFIG_INPUTS: tuple[str, ...] = (
    "configs/v2/generation.yaml",
    "configs/v2/features.yaml",
    "configs/v2/split.yaml",
    "configs/v2/training.yaml",
    "configs/v2/policy.yaml",
)

DEVELOPMENT_DATA_MANIFESTS: tuple[str, ...] = (
    "data/v2/development/manifest.json",
    "data/v2/development/device_splits.csv",
)

PHASE2B_SOURCE_INPUTS: tuple[str, ...] = (
    "src/card_testing_sentinel/v2/phase2b/features.py",
    "src/card_testing_sentinel/v2/phase2b/engine.py",
    "src/card_testing_sentinel/v2/phase2b/batch.py",
    "src/card_testing_sentinel/v2/phase2b/artifacts.py",
    "src/card_testing_sentinel/v2/phase2b/training.py",
    "src/card_testing_sentinel/v2/phase2b/freeze_manifest.py",
    "scripts/v2/phase2b/train_development.py",
)

PHASE2B_CONFIG_INPUTS: tuple[str, ...] = (
    "configs/v2/phase2b/features.yaml",
    "configs/v2/phase2b/training.yaml",
    "configs/v2/phase2b/policy_grid_proposal.yaml",
    "configs/v2/phase2b/requirements-lock.txt",
    "configs/v2/policy.yaml",
)

FORBIDDEN_PHASE2B_ARTIFACTS: tuple[str, ...] = (
    "data/v2/phase2b/fresh_validation",
    "data/v2/phase2b/blind",
    "artifacts/v2/phase2b/fresh_validation",
    "artifacts/v2/phase2b/blind",
    "artifacts/v2/phase2b/policy/frozen_policy.json",
    "artifacts/v2/phase2b/phase3",
    "src/card_testing_sentinel/v2/phase2b/api.py",
    "src/card_testing_sentinel/v2/phase2b/dashboard.py",
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_commit(root: Path = ROOT) -> str | None:
    """Best-effort, read-only ``git rev-parse HEAD``. Never mutates git state
    and never raises -- returns None if git is unavailable or the call fails,
    letting the caller decide (via ``require_git_commit``) whether that is
    acceptable."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def hash_existing_category(paths: tuple[str, ...], root: Path = ROOT) -> dict[str, str]:
    """Hash every path in ``paths`` relative to ``root``. Fails closed: raises
    ``FileNotFoundError`` naming every missing path if any are absent, rather
    than silently hashing a partial set."""
    hashes: dict[str, str] = {}
    missing: list[str] = []
    for rel in paths:
        candidate = root / rel
        if not candidate.exists():
            missing.append(rel)
            continue
        hashes[rel] = sha256_file(candidate)
    if missing:
        raise FileNotFoundError(f"required manifest inputs missing: {missing}")
    return hashes


def assert_absent_category(paths: tuple[str, ...], root: Path = ROOT) -> None:
    """Guard for categories (fresh validation, blind) that must not exist yet.
    Fails closed: raises ``PermissionError`` naming every path that already
    exists, so a manifest can never be built as if a one-time-access boundary
    had already been crossed."""
    present = [rel for rel in paths if (root / rel).exists()]
    if present:
        raise PermissionError(
            f"category must remain absent until explicitly authorized: {present}"
        )


def build_phase2b_freeze_manifest(
    *,
    root: Path = ROOT,
    phase2b_development_artifacts: tuple[str, ...],
    fresh_validation_artifacts: tuple[str, ...] = (),
    blind_artifacts: tuple[str, ...] = (),
    candidate_grid_spec: dict,
    budgets_and_objective_spec: dict,
    created_utc: str,
    require_git_commit: bool = True,
) -> dict:
    """Build (but do not write) a Phase 2B freeze manifest. Every hashed
    category fails closed on a missing or inaccessible file; the two
    not-yet-permitted categories fail closed if they already exist.

    This function performs no filesystem writes. Persisting the result (and
    thereby actually "freezing" something) is a decision explicitly left to
    a future, separately-authorized phase.
    """
    historical = hash_existing_category(HISTORICAL_PHASE2_INPUTS, root)
    source = hash_existing_category(SOURCE_CODE_INPUTS, root)
    config = hash_existing_category(CONFIG_INPUTS, root)
    dev_data = hash_existing_category(DEVELOPMENT_DATA_MANIFESTS, root)
    phase2b_dev = hash_existing_category(phase2b_development_artifacts, root)

    assert_absent_category(fresh_validation_artifacts, root)
    assert_absent_category(blind_artifacts, root)

    commit = git_commit(root)
    if require_git_commit and commit is None:
        raise RuntimeError("git commit hash required but unavailable")

    return {
        "created_utc": created_utc,
        "python_version": sys.version,
        "platform": platform.platform(),
        "git_commit": commit,
        "candidate_grid_spec": candidate_grid_spec,
        "budgets_and_objective_spec": budgets_and_objective_spec,
        "categories": {
            HISTORICAL_CATEGORY: historical,
            SOURCE_CATEGORY: source,
            CONFIG_CATEGORY: config,
            DEV_DATA_CATEGORY: dev_data,
            PHASE2B_DEVELOPMENT_CATEGORY: phase2b_dev,
            FRESH_VALIDATION_CATEGORY: {},
            BLIND_CATEGORY: {},
        },
    }


def verify_manifest_against_disk(
    manifest: dict, root: Path = ROOT
) -> dict[str, list[str]]:
    """Return, per category, the list of ``MISSING:<path>`` / ``CHANGED:<path>``
    problems found when re-hashing the manifest's recorded categories against
    the current filesystem. An empty dict means everything still matches."""
    mismatches: dict[str, list[str]] = {}
    for category, recorded in manifest["categories"].items():
        bad: list[str] = []
        for rel, expected_hash in recorded.items():
            candidate = root / rel
            if not candidate.exists():
                bad.append(f"MISSING:{rel}")
            elif sha256_file(candidate) != expected_hash:
                bad.append(f"CHANGED:{rel}")
        if bad:
            mismatches[category] = bad
    return mismatches


def verify_manifest_strict(manifest: dict, root: Path = ROOT) -> None:
    """Fail closed: raise ``PermissionError`` if any recorded file is missing
    or has changed since the manifest was built."""
    mismatches = verify_manifest_against_disk(manifest, root)
    if mismatches:
        raise PermissionError(
            f"Phase 2B freeze-manifest verification failed: {mismatches}"
        )


def write_training_freeze(
    *,
    root: Path,
    output_dir: Path,
    protected_outputs: tuple[str, ...],
    created_utc: str,
    runtime: dict,
    reproduction: dict,
    policy_search: dict,
) -> tuple[Path, str]:
    """Atomically write the real Phase 2B training freeze and its digest."""
    assert_absent_category(FORBIDDEN_PHASE2B_ARTIFACTS, root)
    if policy_search.get("candidate_count") != 78:
        raise RuntimeError("training freeze requires the exact 78-policy search")
    manifest = {
        "version": "v2b-training-freeze-1",
        "created_utc": created_utc,
        "git_commit": git_commit(root),
        "runtime": runtime,
        "reproduction": reproduction,
        "policy_search": {
            "candidate_count": policy_search["candidate_count"],
            "family_counts": policy_search["family_counts"],
            "enumeration_sha256": policy_search["enumeration_sha256"],
            "evaluated": False,
        },
        "categories": {
            HISTORICAL_CATEGORY: hash_existing_category(HISTORICAL_PHASE2_INPUTS, root),
            SOURCE_CATEGORY: hash_existing_category(PHASE2B_SOURCE_INPUTS, root),
            CONFIG_CATEGORY: hash_existing_category(PHASE2B_CONFIG_INPUTS, root),
            DEV_DATA_CATEGORY: hash_existing_category(DEVELOPMENT_DATA_MANIFESTS, root),
            PHASE2B_DEVELOPMENT_CATEGORY: hash_existing_category(
                protected_outputs, root
            ),
            FRESH_VALIDATION_CATEGORY: {},
            BLIND_CATEGORY: {},
            "operational_policy": {},
            "phase3": {},
            "v2_api": {},
            "v2_dashboard": {},
        },
        "forbidden_artifacts": list(FORBIDDEN_PHASE2B_ARTIFACTS),
    }
    freeze_path = output_dir / "freeze/training_freeze.json"
    digest_path = output_dir / "freeze/training_freeze.sha256"
    atomic_write_json(freeze_path, manifest)
    digest = sha256_file(freeze_path)
    atomic_write_text(digest_path, digest + "\n")
    verify_training_freeze_file(freeze_path, digest_path, root=root)
    return freeze_path, digest


def verify_training_freeze_file(
    freeze_path: Path, digest_path: Path, *, root: Path = ROOT
) -> dict:
    """Fail closed on digest drift, protected-file drift, or forbidden material."""
    if not freeze_path.is_file() or not digest_path.is_file():
        raise FileNotFoundError("Phase 2B training freeze or digest is missing")
    expected = digest_path.read_text().strip()
    if sha256_file(freeze_path) != expected:
        raise PermissionError("Phase 2B training freeze digest mismatch")
    manifest = json.loads(freeze_path.read_text())
    verify_manifest_strict(manifest, root)
    assert_absent_category(tuple(manifest["forbidden_artifacts"]), root)
    if manifest["policy_search"]["candidate_count"] != 78:
        raise PermissionError("Phase 2B frozen policy enumeration count changed")
    return manifest
