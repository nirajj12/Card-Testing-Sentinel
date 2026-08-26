import json
from pathlib import Path

import pandas as pd
import yaml

from card_testing_sentinel.v2.evaluation.access import (
    ROOT,
    sha256_file,
    verify_phase1_protected_inputs,
    verify_training_freeze,
    verify_v1_release,
)


def _budget_excess(budgets: dict) -> tuple[int, list[dict]]:
    failures = []
    total = 0
    for subgroup, values in budgets.items():
        review_excess = max(0, values["review_or_higher"] - values["review_allowance"])
        block_excess = max(0, values["block"] - values["block_allowance"])
        total += review_excess + block_excess
        if review_excess or block_excess:
            failures.append(
                {
                    "subgroup": subgroup,
                    "review_or_higher": values["review_or_higher"],
                    "review_allowance": values["review_allowance"],
                    "review_excess": review_excess,
                    "block": values["block"],
                    "block_allowance": values["block_allowance"],
                    "block_excess": block_excess,
                }
            )
    return total, failures


def write_blocked_report(root: Path = ROOT) -> dict:
    freeze = verify_training_freeze()
    verify_phase1_protected_inputs()
    verify_v1_release()
    table_path = root / "artifacts/v2/metrics/validation_policy_candidates.csv"
    table = pd.read_csv(table_path)
    if table.empty or bool(table.feasible.any()):
        raise RuntimeError(
            "blocked report requires a complete grid with no feasible policy"
        )
    policy_config = yaml.safe_load((root / "configs/v2/policy.yaml").read_text())
    access = json.loads(
        (root / "artifacts/v2/training/first_validation_access.json").read_text()
    )
    closest = {}
    for family, group in table.groupby("family", sort=True):
        ranked = []
        for row in group.itertuples():
            budgets = json.loads(row.budget_results_json)
            excess, failures = _budget_excess(budgets)
            ranked.append((excess, row.candidate_id, row, failures))
        excess, _, row, failures = min(ranked, key=lambda value: (value[0], value[1]))
        closest[str(family)] = {
            "candidate_id": row.candidate_id,
            "parameters": json.loads(row.parameters_json),
            "total_devices_over_allowances": excess,
            "failures": failures,
            "worst_subtype_review_coverage": row.worst_subtype_review_coverage,
            "macro_subtype_review_coverage": row.macro_subtype_review_coverage,
            "worst_subtype_block_coverage": row.worst_subtype_block_coverage,
            "macro_subtype_block_coverage": row.macro_subtype_block_coverage,
            "objective_tuple": json.loads(row.objective_tuple_json),
        }
    payload = {
        "status": "blocked_no_feasible_policy",
        "training_freeze_sha256": sha256_file(
            root / "artifacts/v2/training/training_freeze.json"
        ),
        "training_freeze_created_utc": freeze["created_utc"],
        "first_validation_access_utc": access["first_validation_access_utc"],
        "candidate_count": int(len(table)),
        "feasible_candidate_count": 0,
        "family_candidate_counts": {
            str(key): int(value)
            for key, value in table.groupby("family").size().items()
        },
        "frozen_budgets": policy_config["budgets"],
        "closest_candidates_by_family": closest,
        "frozen_choices_changed_after_validation": False,
        "frozen_policy_created": False,
        "blind_challenge_created_or_accessed": False,
    }
    metrics_path = root / "artifacts/v2/metrics/validation_blocked_metrics.json"
    metrics_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    rules = closest["rules_only"]
    ml = closest["ml_only"]
    combined = closest["combined"]
    report = [
        "# V2 Phase 2 blocked at validation policy gate",
        "",
        (
            f"The training freeze was created at `{freeze['created_utc']}` and "
            f"validation was first opened at `{access['first_validation_access_utc']}`."
        ),
        "",
        (
            f"All {len(table)} candidates in the frozen grid were evaluated with "
            "intervention-aware raw lifecycle replay. Zero candidates met every "
            "overall and subgroup allowance, so no V2 policy was selected or frozen."
        ),
        "",
        "## Exact closest boundaries",
        "",
        (
            f"- Rules-only `{rules['candidate_id']}` exceeded only normal_bad_luck "
            "review-or-higher: 6/100 against an allowance of 5/100. Its "
            f"worst-subtype attacker review coverage was "
            f"{rules['worst_subtype_review_coverage']:.4f}."
        ),
        (
            f"- ML-only `{ml['candidate_id']}` was "
            f"{ml['total_devices_over_allowances']} device-count units over frozen "
            "subgroup allowances; see the machine-readable failures for exact "
            "review/block counts."
        ),
        (
            f"- Combined `{combined['candidate_id']}` was "
            f"{combined['total_devices_over_allowances']} device-count "
            "units over frozen subgroup allowances."
        ),
        "",
        (
            "The budgets, rules, feature list, model, calibration, policy forms, "
            "thresholds, grids, objective and metric definitions were not changed "
            "after validation access. The candidate table retains the exact "
            "comparison tuple and budget results for every candidate."
        ),
    ]
    report_path = root / "reports/v2/modeling/validation_policy_blocked.md"
    report_path.write_text("\n".join(report) + "\n")
    hashes = {
        "artifacts/v2/metrics/validation_policy_candidates.csv": sha256_file(
            table_path
        ),
        "artifacts/v2/metrics/validation_blocked_metrics.json": sha256_file(
            metrics_path
        ),
        "reports/v2/modeling/validation_policy_blocked.md": sha256_file(report_path),
    }
    manifest_path = root / "artifacts/v2/phase2_blocked_artifact_hashes.json"
    manifest_path.write_text(json.dumps(hashes, indent=2, sort_keys=True) + "\n")
    return payload
