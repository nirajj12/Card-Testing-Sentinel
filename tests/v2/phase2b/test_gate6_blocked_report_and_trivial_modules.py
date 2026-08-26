"""Gate 6 (corrective pass, continued): exercise the previously-0%-covered
``v2.policy.blocked`` and ``v2.policy.engine`` modules.

``write_blocked_report`` writes its outputs relative to a caller-supplied
``root`` parameter, so it is exercised here against a fully synthetic
temporary "fake repo" -- never against this project's real, historical
``artifacts/v2/metrics/validation_blocked_metrics.json`` or
``reports/v2/modeling/validation_policy_blocked.md``, which remain
untouched. The freeze/protected-input guards it calls internally
(``verify_training_freeze``, ``verify_phase1_protected_inputs``,
``verify_v1_release``) are NOT parameterized by ``root`` -- they always
check this project's real, unmodified evidence, so this test also doubles
as a live check that those guards still pass.
"""

import json

import pandas as pd
import yaml

from card_testing_sentinel.v2.policy import blocked, engine


def _write(root, rel, content):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, str):
        path.write_text(content)
    else:
        path.write_text(json.dumps(content))
    return path


def _candidate_row(candidate_id, family, review_excess=0, block_excess=0):
    budgets = {
        "overall_legitimate": {
            "review_or_higher": review_excess,
            "review_allowance": 0,
            "block": block_excess,
            "block_allowance": 0,
        }
    }
    return {
        "candidate_id": candidate_id,
        "family": family,
        "parameters_json": json.dumps({"x": 1}),
        "feasible": False,
        "worst_subtype_review_coverage": 0.5,
        "macro_subtype_review_coverage": 0.5,
        "worst_subtype_block_coverage": 0.5,
        "macro_subtype_block_coverage": 0.5,
        "objective_tuple_json": json.dumps([0.5]),
        "budget_results_json": json.dumps(budgets),
    }


def _fake_root(tmp_path):
    root = tmp_path / "fake_repo"
    table = pd.DataFrame(
        [
            _candidate_row("policy_000", "rules_only", review_excess=1),
            _candidate_row("policy_001", "ml_only", block_excess=2),
            _candidate_row("policy_002", "combined", review_excess=1, block_excess=1),
        ]
    )
    table_path = _write(
        root, "artifacts/v2/metrics/validation_policy_candidates.csv", ""
    )
    table.to_csv(table_path, index=False)
    _write(
        root,
        "configs/v2/policy.yaml",
        yaml.safe_dump({"budgets": {"overall_legitimate": {"denominator": 100}}}),
    )
    _write(
        root,
        "artifacts/v2/training/first_validation_access.json",
        {"first_validation_access_utc": "2026-01-01T00:00:00+00:00"},
    )
    _write(root, "artifacts/v2/training/training_freeze.json", "{}")
    # write_blocked_report() does not create this output directory itself.
    (root / "reports/v2/modeling").mkdir(parents=True, exist_ok=True)
    return root


def test_write_blocked_report_against_a_synthetic_root(tmp_path):
    from card_testing_sentinel.v2.evaluation.access import ROOT, sha256_file

    real_metrics_path = ROOT / "artifacts/v2/metrics/validation_blocked_metrics.json"
    real_metrics_hash_before = sha256_file(real_metrics_path)

    root = _fake_root(tmp_path)
    payload = blocked.write_blocked_report(root=root)

    assert sha256_file(real_metrics_path) == real_metrics_hash_before

    assert payload["status"] == "blocked_no_feasible_policy"
    assert payload["candidate_count"] == 3
    assert payload["feasible_candidate_count"] == 0
    assert set(payload["family_candidate_counts"]) == {
        "rules_only",
        "ml_only",
        "combined",
    }
    assert payload["closest_candidates_by_family"]["rules_only"]["candidate_id"] == (
        "policy_000"
    )
    assert (root / "artifacts/v2/metrics/validation_blocked_metrics.json").exists()
    assert (root / "reports/v2/modeling/validation_policy_blocked.md").exists()
    assert (root / "artifacts/v2/phase2_blocked_artifact_hashes.json").exists()


def test_write_blocked_report_rejects_a_table_with_a_feasible_candidate(tmp_path):
    root = _fake_root(tmp_path)
    table_path = root / "artifacts/v2/metrics/validation_policy_candidates.csv"
    table = pd.read_csv(table_path)
    table.loc[0, "feasible"] = True
    table.to_csv(table_path, index=False)

    import pytest

    with pytest.raises(RuntimeError, match="no feasible policy"):
        blocked.write_blocked_report(root=root)


def test_budget_excess_reports_zero_for_within_budget_groups():
    total, failures = blocked._budget_excess(
        {
            "overall_legitimate": {
                "review_or_higher": 3,
                "review_allowance": 5,
                "block": 0,
                "block_allowance": 2,
            }
        }
    )
    assert total == 0
    assert failures == []


def test_budget_excess_reports_exact_excess_for_over_budget_groups():
    total, failures = blocked._budget_excess(
        {
            "normal_bad_luck": {
                "review_or_higher": 6,
                "review_allowance": 5,
                "block": 3,
                "block_allowance": 1,
            }
        }
    )
    assert total == 1 + 2  # review excess 1, block excess 2
    assert failures[0]["subgroup"] == "normal_bad_luck"
    assert failures[0]["review_excess"] == 1
    assert failures[0]["block_excess"] == 2


def test_policy_engine_reexports_choose_action():
    assert engine.choose_action is not None
    assert engine.__all__ == ["choose_action"]
