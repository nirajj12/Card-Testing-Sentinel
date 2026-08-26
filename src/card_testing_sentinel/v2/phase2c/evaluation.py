"""Exactly-once Phase 2C confirmation evaluation."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path

import joblib
import pandas as pd
import yaml

from card_testing_sentinel.common.atomic_io import atomic_write_json, atomic_write_text
from card_testing_sentinel.v2.phase2b.validation_policy import (
    OptimizedFrozenScorer,
    verify_allow_all_parity,
)
from card_testing_sentinel.v2.phase2c.confirmation import (
    CONFIRMATION_RELATIVE_PATH,
    EVALUATION_RELATIVE_PATH,
    FREEZE_RELATIVE_PATH,
    ROOT,
    open_confirmation_once,
    sha256_file,
    verify_confirmation_lifecycle,
    verify_development_freeze,
)
from card_testing_sentinel.v2.phase2c.replay import (
    candidate_metrics,
    replay_stateful_candidate,
    selection_key,
)


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    atomic_write_text(
        path,
        frame.to_csv(index=False, lineterminator="\n", float_format="%.12g"),
    )


def _candidate_row(candidate: dict, metrics: dict, audit: dict) -> dict:
    median = metrics["intervention_distributions"][
        "requests_scored_through_first_action"
    ]["median"]
    row = {
        "candidate_id": candidate["candidate_id"],
        "family": candidate["family"],
        "parameters_json": json.dumps(candidate, sort_keys=True),
        "feasible": metrics["feasible"],
        "safety_passed": metrics["safety_passed"],
        "effectiveness_passed": metrics["effectiveness_passed"],
        "failed_constraints_json": json.dumps(metrics["failed_constraints"]),
        "worst_subtype_review_coverage": metrics["worst_subtype_review_coverage"],
        "overall_attacker_review_coverage": metrics["attacker_review_or_higher"][
            "rate"
        ],
        "overall_attacker_block_coverage": metrics["attacker_block"]["rate"],
        "median_attempts_through_first_intervention": median,
        "legitimate_review_or_higher": metrics["legitimate_review_or_higher"],
        "legitimate_blocks": metrics["legitimate_blocks"],
        "never_detected_attackers": metrics["never_detected_attackers"],
        "potentially_preventable_later_attempts_offline_upper_bound": metrics[
            "potentially_preventable_later_attempts_offline_upper_bound"
        ],
        "reason_code_frequencies_json": json.dumps(
            audit["reason_code_frequencies"], sort_keys=True
        ),
        "selection_key_json": json.dumps(selection_key(candidate, metrics)),
        "metrics_json": json.dumps(metrics, sort_keys=True),
        "audit_json": json.dumps(audit, sort_keys=True),
    }
    for name, budget in metrics["budget_results"].items():
        row[f"budget_{name}_review"] = budget["review_or_higher_devices"]
        row[f"budget_{name}_review_allowance"] = budget["review_allowance_devices"]
        row[f"budget_{name}_block"] = budget["block_devices"]
        row[f"budget_{name}_block_allowance"] = budget["block_allowance_devices"]
    for subtype, values in metrics["subtype"].items():
        row[f"{subtype}_review_coverage"] = values["review_or_higher"]["rate"]
        row[f"{subtype}_block_coverage"] = values["block"]["rate"]
        row[f"{subtype}_never_detected"] = values["never_detected"]
    for limit, values in metrics["within_attempt"].items():
        row[f"detected_within_{limit}"] = values["review_or_higher"]
        row[f"blocked_within_{limit}"] = values["block"]
    return row


def _write_final_manifest(root: Path, relative_paths: list[str]) -> tuple[Path, str]:
    output = root / EVALUATION_RELATIVE_PATH
    manifest_path = output / "final_hash_manifest.json"
    payload = {
        "version": "v2-phase2c-confirmation-final-manifest-1",
        "created_utc": datetime.now(UTC).isoformat(),
        "protected_hashes": {
            name: sha256_file(root / name) for name in sorted(relative_paths)
        },
        "blind_evaluated": False,
    }
    atomic_write_json(manifest_path, payload)
    digest = sha256_file(manifest_path)
    atomic_write_text(manifest_path.with_suffix(".sha256"), digest + "\n")
    return manifest_path, digest


def run_confirmation(root: Path = ROOT) -> dict:
    """Open confirmation once, evaluate the frozen 20 candidates, and stop."""
    started = time.perf_counter()
    freeze = verify_development_freeze(root)
    raw, contract, ledger = open_confirmation_once(root)
    output = root / EVALUATION_RELATIVE_PATH
    config = yaml.safe_load((root / "configs/v2/phase2c/policy.yaml").read_text())
    candidates = freeze["candidates"]
    if len(candidates) != freeze["candidate_count"]:
        raise PermissionError("frozen candidate count mismatch")
    model = joblib.load(
        root / "artifacts/v2/phase2b/training/models/selected_model.joblib"
    )
    scorer = OptimizedFrozenScorer(model)
    allow_all_features, feature_parity = verify_allow_all_parity(raw)
    probability_parity = scorer.verify_parity(
        allow_all_features.head(512), float(config["parity_tolerance"])
    )
    parity = {
        "feature_parity": feature_parity,
        "optimized_probability_parity": probability_parity,
        "frozen_model_loaded_once": True,
    }
    atomic_write_json(output / "allow_all_parity.json", parity)

    replay_started = time.perf_counter()
    candidate_records = []
    result_rows = []
    requests = int(raw.event_type.eq("authorization_request").sum())
    for candidate in candidates:
        _decisions, devices, audit = replay_stateful_candidate(
            raw, contract, scorer, candidate
        )
        metrics = candidate_metrics(
            devices,
            config["safety_rates"],
            config["effectiveness_targets"],
        )
        record = {"candidate": candidate, "metrics": metrics, "audit": audit}
        candidate_records.append(record)
        result_rows.append(_candidate_row(candidate, metrics, audit))
    replay_seconds = time.perf_counter() - replay_started
    feasible = [row for row in candidate_records if row["metrics"]["feasible"]]
    feasible.sort(key=lambda row: selection_key(row["candidate"], row["metrics"]))
    champion = feasible[0] if feasible else None

    candidate_table = pd.DataFrame(result_rows).sort_values("candidate_id")
    _write_csv(candidate_table, output / "candidate_results.csv")
    atomic_write_json(
        output / "candidate_metrics.json",
        {row["candidate"]["candidate_id"]: row for row in candidate_records},
    )
    reproduction = None
    policy_digest = None
    if champion is not None:
        decisions, devices, audit = replay_stateful_candidate(
            raw,
            contract,
            scorer,
            champion["candidate"],
            capture_decisions=True,
        )
        reproduced_metrics = candidate_metrics(
            devices,
            config["safety_rates"],
            config["effectiveness_targets"],
        )
        reproduction = {
            "passed": json.dumps(reproduced_metrics, sort_keys=True)
            == json.dumps(champion["metrics"], sort_keys=True),
            "metrics": reproduced_metrics,
            "audit": audit,
        }
        if not reproduction["passed"]:
            raise RuntimeError("confirmation champion did not reproduce exactly")
        _write_csv(decisions, output / "champion_decisions.csv")
        _write_csv(devices, output / "champion_device_summary.csv")
        frozen_policy = {
            "version": "v2-phase2c-operational-policy-1",
            "selected_utc": datetime.now(UTC).isoformat(),
            "policy": champion["candidate"],
            "metrics": champion["metrics"],
            "reason_code_contract": freeze["reason_code_contract"],
            "state_schema_version": freeze["state_schema_version"],
            "model_contract": freeze["model_contract"],
            "development_freeze_sha256": sha256_file(root / FREEZE_RELATIVE_PATH),
            "dataset_manifest_sha256": sha256_file(
                root / CONFIRMATION_RELATIVE_PATH / "manifest.json"
            ),
            "phase2b_policy_preserved": True,
            "blind_evaluated": False,
        }
        policy_path = output / "frozen_operational_policy.json"
        atomic_write_json(policy_path, frozen_policy)
        policy_digest = sha256_file(policy_path)
        atomic_write_text(
            output / "frozen_operational_policy.sha256", policy_digest + "\n"
        )
        phase2b_policy = json.loads(
            (
                root / "artifacts/v2/phase2b/validation/frozen_operational_policy.json"
            ).read_text()
        )
        comparison = {
            "phase2b": {
                "policy_sha256": sha256_file(
                    root
                    / "artifacts/v2/phase2b/validation/frozen_operational_policy.json"
                ),
                "metrics": phase2b_policy["metrics"],
            },
            "phase2c": {
                "policy_sha256": policy_digest,
                "metrics": champion["metrics"],
            },
            "delta": {
                "attacker_review_or_higher_rate": champion["metrics"][
                    "attacker_review_or_higher"
                ]["rate"]
                - phase2b_policy["metrics"]["attacker_review_or_higher"]["rate"],
                "attacker_block_rate": champion["metrics"]["attacker_block"]["rate"]
                - phase2b_policy["metrics"]["attacker_block"]["rate"],
                "never_detected_attackers": champion["metrics"][
                    "never_detected_attackers"
                ]
                - phase2b_policy["metrics"]["never_detected_attackers"],
            },
        }
        atomic_write_json(output / "phase2b_vs_phase2c.json", comparison)

    status = "completed_feasible" if champion is not None else "completed_blocked"
    feasibility = {
        "status": status,
        "candidate_count": len(candidates),
        "feasible_candidate_count": len(feasible),
        "champion": champion,
        "reproduction": reproduction,
        "no_target_or_budget_changes_after_access": True,
        "additional_confirmation_generation_authorized": False,
        "blind_evaluated": False,
    }
    atomic_write_json(output / "feasibility.json", feasibility)
    runtime = {
        "candidate_count": len(candidates),
        "requests_per_candidate": requests,
        "candidate_requests": requests * len(candidates),
        "causal_replay_seconds": replay_seconds,
        "candidate_requests_per_second": requests * len(candidates) / replay_seconds,
        "total_seconds_before_manifest": time.perf_counter() - started,
        "frozen_model_loaded_once": True,
        "per_request_dataframes": False,
        "deterministic_result_ordering": True,
    }
    atomic_write_json(output / "runtime.json", runtime)
    ledger.update(
        {
            "completed_utc": datetime.now(UTC).isoformat(),
            "status": status,
            "candidates_evaluated": len(candidates),
            "feasible_candidate_count": len(feasible),
            "frozen_operational_policy_sha256": policy_digest,
        }
    )
    atomic_write_json(output / "access_ledger.json", ledger)
    protected = [
        str(FREEZE_RELATIVE_PATH),
        str(CONFIRMATION_RELATIVE_PATH / "manifest.json"),
        str(EVALUATION_RELATIVE_PATH / "access_ledger.json"),
        str(EVALUATION_RELATIVE_PATH / "allow_all_parity.json"),
        str(EVALUATION_RELATIVE_PATH / "candidate_results.csv"),
        str(EVALUATION_RELATIVE_PATH / "candidate_metrics.json"),
        str(EVALUATION_RELATIVE_PATH / "feasibility.json"),
        str(EVALUATION_RELATIVE_PATH / "runtime.json"),
    ]
    if champion is not None:
        protected.extend(
            str(EVALUATION_RELATIVE_PATH / name)
            for name in (
                "champion_decisions.csv",
                "champion_device_summary.csv",
                "frozen_operational_policy.json",
                "frozen_operational_policy.sha256",
                "phase2b_vs_phase2c.json",
            )
        )
    _manifest_path, manifest_digest = _write_final_manifest(root, protected)
    report = [
        "# Phase 2C one-time confirmation evaluation",
        "",
        f"- Status: {status}",
        f"- Candidates evaluated exactly once: {len(candidates)}",
        f"- Feasible candidates: {len(feasible)}",
        f"- Champion: {champion['candidate']['candidate_id'] if champion else 'none'}",
        f"- Candidate-requests/second: {runtime['candidate_requests_per_second']:.2f}",
        "- Blind data accessed: no",
        "- Another confirmation generation or evaluation: refused",
    ]
    atomic_write_text(
        root / "reports/v2/phase2c/confirmation_evaluation.md",
        "\n".join(report) + "\n",
    )
    verify_confirmation_lifecycle(root=root, state="post_scoring")
    return {
        "status": status,
        "candidate_count": len(candidates),
        "feasible_candidate_count": len(feasible),
        "champion": champion,
        "operational_policy_sha256": policy_digest,
        "final_manifest_sha256": manifest_digest,
        "runtime": runtime,
    }
