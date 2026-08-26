"""Gate F: tests for the reusable Phase 2B freeze-manifest builder.

These tests build synthetic, temporary-directory "fake repos" so the
manifest-builder mechanism can be proven correct (fail-closed on missing or
changed files, and on a premature fresh-validation/blind read) WITHOUT ever
building a real Phase 2B freeze against this project's actual artifacts.
"""

from pathlib import Path

import pytest

from card_testing_sentinel.v2.phase2b.freeze_manifest import (
    assert_absent_category,
    build_phase2b_freeze_manifest,
    hash_existing_category,
    sha256_file,
    verify_manifest_against_disk,
    verify_manifest_strict,
)


def _write(root: Path, rel: str, content: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _fake_repo(tmp_path: Path) -> Path:
    """A minimal synthetic repo satisfying every category path the real
    builder expects, so build_phase2b_freeze_manifest() can run end-to-end
    against fixtures instead of the real project tree."""
    from card_testing_sentinel.v2.phase2b import freeze_manifest as fm

    root = tmp_path / "fake_repo"
    for rel in (
        *fm.HISTORICAL_PHASE2_INPUTS,
        *fm.SOURCE_CODE_INPUTS,
        *fm.CONFIG_INPUTS,
        *fm.DEVELOPMENT_DATA_MANIFESTS,
    ):
        _write(root, rel, f"synthetic fixture content for {rel}\n")
    _write(root, "artifacts/v2/phase2b/models/candidate.joblib", "fake-model-bytes\n")
    _write(
        root,
        "artifacts/v2/phase2b/metrics/oof_metrics.csv",
        "device_id,score\nd1,0.5\n",
    )
    return root


def test_hash_existing_category_fails_closed_on_missing_file(tmp_path):
    root = tmp_path
    _write(root, "present.txt", "hello")
    with pytest.raises(FileNotFoundError, match="missing.txt"):
        hash_existing_category(("present.txt", "missing.txt"), root=root)


def test_hash_existing_category_succeeds_when_all_present(tmp_path):
    root = tmp_path
    _write(root, "a.txt", "alpha")
    _write(root, "b.txt", "beta")
    hashes = hash_existing_category(("a.txt", "b.txt"), root=root)
    assert hashes == {
        "a.txt": sha256_file(root / "a.txt"),
        "b.txt": sha256_file(root / "b.txt"),
    }


def test_assert_absent_category_passes_when_truly_absent(tmp_path):
    assert_absent_category(("fresh_validation/does_not_exist.csv",), root=tmp_path)


def test_assert_absent_category_fails_closed_when_present(tmp_path):
    root = tmp_path
    _write(root, "blind/challenge.csv", "should not exist yet")
    with pytest.raises(PermissionError, match="challenge.csv"):
        assert_absent_category(("blind/challenge.csv",), root=root)


def test_build_manifest_end_to_end_against_synthetic_repo(tmp_path):
    root = _fake_repo(tmp_path)
    manifest = build_phase2b_freeze_manifest(
        root=root,
        phase2b_development_artifacts=(
            "artifacts/v2/phase2b/models/candidate.joblib",
            "artifacts/v2/phase2b/metrics/oof_metrics.csv",
        ),
        fresh_validation_artifacts=(
            "artifacts/v2/phase2b/fresh_validation/holdout.csv",
        ),
        blind_artifacts=("artifacts/v2/phase2b/blind/challenge.csv",),
        candidate_grid_spec={"family_count": 3, "total_candidates": 41},
        budgets_and_objective_spec={
            "review_budget": 0.05,
            "objective": "worst_subtype_recall",
        },
        created_utc="2026-08-25T00:00:00+00:00",
        require_git_commit=False,
    )
    assert manifest["categories"]["fresh_validation"] == {}
    assert manifest["categories"]["blind"] == {}
    assert len(manifest["categories"]["historical_phase2"]) == 7
    assert len(manifest["categories"]["phase2b_development"]) == 2
    # Round-trips cleanly against the same synthetic tree with no drift yet.
    assert verify_manifest_against_disk(manifest, root=root) == {}
    verify_manifest_strict(manifest, root=root)  # must not raise


def test_build_manifest_fails_closed_when_fresh_validation_already_exists(tmp_path):
    root = _fake_repo(tmp_path)
    _write(root, "artifacts/v2/phase2b/fresh_validation/holdout.csv", "leaked early")
    with pytest.raises(PermissionError, match="holdout.csv"):
        build_phase2b_freeze_manifest(
            root=root,
            phase2b_development_artifacts=(),
            fresh_validation_artifacts=(
                "artifacts/v2/phase2b/fresh_validation/holdout.csv",
            ),
            blind_artifacts=(),
            candidate_grid_spec={},
            budgets_and_objective_spec={},
            created_utc="2026-08-25T00:00:00+00:00",
            require_git_commit=False,
        )


def test_build_manifest_fails_closed_when_blind_already_exists(tmp_path):
    root = _fake_repo(tmp_path)
    _write(root, "artifacts/v2/phase2b/blind/challenge.csv", "leaked early")
    with pytest.raises(PermissionError, match="challenge.csv"):
        build_phase2b_freeze_manifest(
            root=root,
            phase2b_development_artifacts=(),
            fresh_validation_artifacts=(),
            blind_artifacts=("artifacts/v2/phase2b/blind/challenge.csv",),
            candidate_grid_spec={},
            budgets_and_objective_spec={},
            created_utc="2026-08-25T00:00:00+00:00",
            require_git_commit=False,
        )


def test_build_manifest_fails_closed_when_a_historical_input_is_missing(tmp_path):
    root = _fake_repo(tmp_path)
    (root / "reports/v2/modeling/phase2_final_closeout.md").unlink()
    with pytest.raises(FileNotFoundError, match="phase2_final_closeout.md"):
        build_phase2b_freeze_manifest(
            root=root,
            phase2b_development_artifacts=(),
            candidate_grid_spec={},
            budgets_and_objective_spec={},
            created_utc="2026-08-25T00:00:00+00:00",
            require_git_commit=False,
        )


def test_build_manifest_requires_git_commit_by_default(tmp_path):
    root = _fake_repo(tmp_path)  # not a git repo -- git rev-parse will fail
    with pytest.raises(RuntimeError, match="git commit"):
        build_phase2b_freeze_manifest(
            root=root,
            phase2b_development_artifacts=(),
            candidate_grid_spec={},
            budgets_and_objective_spec={},
            created_utc="2026-08-25T00:00:00+00:00",
        )


def test_verify_manifest_strict_fails_closed_on_post_build_drift(tmp_path):
    root = _fake_repo(tmp_path)
    manifest = build_phase2b_freeze_manifest(
        root=root,
        phase2b_development_artifacts=("artifacts/v2/phase2b/models/candidate.joblib",),
        candidate_grid_spec={},
        budgets_and_objective_spec={},
        created_utc="2026-08-25T00:00:00+00:00",
        require_git_commit=False,
    )
    # Simulate someone editing a hashed source file after the freeze was built.
    _write(
        root, "src/card_testing_sentinel/v2/policy/engine.py", "mutated after freeze\n"
    )
    mismatches = verify_manifest_against_disk(manifest, root=root)
    assert "source_code" in mismatches
    assert any("engine.py" in entry for entry in mismatches["source_code"])
    with pytest.raises(PermissionError, match="freeze-manifest verification failed"):
        verify_manifest_strict(manifest, root=root)


def test_verify_manifest_strict_fails_closed_on_post_build_deletion(tmp_path):
    root = _fake_repo(tmp_path)
    manifest = build_phase2b_freeze_manifest(
        root=root,
        phase2b_development_artifacts=("artifacts/v2/phase2b/models/candidate.joblib",),
        candidate_grid_spec={},
        budgets_and_objective_spec={},
        created_utc="2026-08-25T00:00:00+00:00",
        require_git_commit=False,
    )
    (root / "artifacts/v2/phase2b/models/candidate.joblib").unlink()
    mismatches = verify_manifest_against_disk(manifest, root=root)
    assert any("MISSING" in entry for entry in mismatches["phase2b_development"])
    with pytest.raises(PermissionError):
        verify_manifest_strict(manifest, root=root)
