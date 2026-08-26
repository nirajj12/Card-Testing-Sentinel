"""Authorized continuation of Phase 2C confirmation scoring attempt 1."""

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
from card_testing_sentinel.v2.phase2c.amendment import (
    CONFIRMATION_MANIFEST_SHA256,
    CONFIRMATION_RELATIVE_PATH,
    EVALUATION_RELATIVE_PATH,
    LEDGER_AMENDMENT_PATH,
    LEDGER_COMPLETION_PATH,
    ORIGINAL_LEDGER_SHA256,
    REPLACEMENT_FREEZE_PATH,
    ROOT,
    _assert_no_performance_outputs,
    canonical_runtime,
    refuse_if_already_resumed,
    sha256_file,
    verify_correction_chain,
)
from card_testing_sentinel.v2.phase2c.confirmation import verify_dataset_manifest
from card_testing_sentinel.v2.phase2c.evaluation import (
    _candidate_row,
    _write_csv,
    _write_final_manifest,
)
from card_testing_sentinel.v2.phase2c.replay import (
    candidate_metrics,
    replay_stateful_candidate,
    selection_key,
)


def _write_completion(path: Path, payload: dict) -> str:
    if path.exists() or path.with_suffix(".sha256").exists():
        raise PermissionError("a second confirmation evaluation is refused")
    atomic_write_json(path, payload)
    digest = sha256_file(path)
    atomic_write_text(path.with_suffix(".sha256"), digest + "\n")
    return digest


def _verify_final_manifest(root: Path) -> dict:
    output = root / EVALUATION_RELATIVE_PATH
    path = output / "final_hash_manifest.json"
    digest_path = output / "final_hash_manifest.sha256"
    if not path.is_file() or not digest_path.is_file():
        raise FileNotFoundError("confirmation final manifest is incomplete")
    if sha256_file(path) != digest_path.read_text().strip():
        raise PermissionError("confirmation final manifest digest drift")
    manifest = json.loads(path.read_text())
    for relative, digest in manifest["protected_hashes"].items():
        candidate = root / relative
        if not candidate.is_file() or sha256_file(candidate) != digest:
            raise PermissionError(f"confirmation result drift: {relative}")
    return manifest


def verify_resumed_post_scoring(root: Path = ROOT) -> dict:
    correction = verify_correction_chain(root)
    completion_path = root / LEDGER_COMPLETION_PATH
    completion_digest_path = completion_path.with_suffix(".sha256")
    if not completion_path.is_file() or not completion_digest_path.is_file():
        raise FileNotFoundError("append-only ledger completion is missing")
    if sha256_file(completion_path) != completion_digest_path.read_text().strip():
        raise PermissionError("append-only ledger completion drift")
    completion = json.loads(completion_path.read_text())
    if (
        completion.get("scoring_attempt") != 1
        or completion.get("candidates_evaluated") != 20
        or not str(completion.get("status", "")).startswith("completed_")
        or completion.get("original_access_ledger_sha256") != ORIGINAL_LEDGER_SHA256
        or completion.get("ledger_amendment_sha256")
        != correction["ledger_amendment_sha256"]
    ):
        raise PermissionError("append-only ledger completion is invalid")
    output = root / EVALUATION_RELATIVE_PATH
    required = (
        "allow_all_parity.json",
        "candidate_results.csv",
        "candidate_metrics.json",
        "feasibility.json",
        "runtime.json",
        "final_hash_manifest.json",
        "final_hash_manifest.sha256",
    )
    missing = [name for name in required if not (output / name).is_file()]
    if missing:
        raise PermissionError(f"confirmation outputs incomplete: {missing}")
    feasibility = json.loads((output / "feasibility.json").read_text())
    if feasibility["status"] == "completed_feasible":
        feasible_required = (
            "champion_decisions.csv",
            "champion_device_summary.csv",
            "frozen_operational_policy.json",
            "frozen_operational_policy.sha256",
            "phase2b_vs_phase2c.json",
        )
        missing = [name for name in feasible_required if not (output / name).is_file()]
        if missing:
            raise PermissionError(
                f"feasible confirmation outputs incomplete: {missing}"
            )
    manifest = _verify_final_manifest(root)
    return {
        "passed": True,
        "correction": correction,
        "completion": completion,
        "feasibility": feasibility,
        "manifest": manifest,
    }


def run_resumed_confirmation(root: Path = ROOT) -> dict:
    """Resume the existing unscored attempt; never create attempt 2."""
    started = time.perf_counter()
    runtime_contract = canonical_runtime()
    correction = verify_correction_chain(root)
    refuse_if_already_resumed(root)
    _assert_no_performance_outputs(root)
    dataset = verify_dataset_manifest(root / CONFIRMATION_RELATIVE_PATH)
    if sha256_file(root / CONFIRMATION_RELATIVE_PATH / "manifest.json") != (
        CONFIRMATION_MANIFEST_SHA256
    ):
        raise PermissionError("confirmation manifest drift before resumed scoring")
    raw = pd.read_csv(root / CONFIRMATION_RELATIVE_PATH / "raw_events.csv")
    contract = pd.read_csv(root / CONFIRMATION_RELATIVE_PATH / "device_contract.csv")
    replacement = correction["replacement"]
    candidates = replacement["candidates"]
    if len(candidates) != 20:
        raise PermissionError("replacement freeze must contain exactly 20 candidates")
    config = yaml.safe_load((root / "configs/v2/phase2c/policy.yaml").read_text())
    model = joblib.load(
        root / "artifacts/v2/phase2b/training/models/selected_model.joblib"
    )
    scorer = OptimizedFrozenScorer(model)
    allow_all_features, feature_parity = verify_allow_all_parity(raw)
    probability_parity = scorer.verify_parity(
        allow_all_features.head(512), float(config["parity_tolerance"])
    )
    output = root / EVALUATION_RELATIVE_PATH
    atomic_write_json(
        output / "allow_all_parity.json",
        {
            "feature_parity": feature_parity,
            "optimized_probability_parity": probability_parity,
            "frozen_model_loaded_once": True,
            "canonical_runtime": runtime_contract,
            "resumed_scoring_attempt": 1,
        },
    )
    replay_started = time.perf_counter()
    candidate_records = []
    result_rows = []
    requests = int(raw.event_type.eq("authorization_request").sum())
    for candidate in candidates:
        _decisions, devices, audit = replay_stateful_candidate(
            raw, contract, scorer, candidate
        )
        if audit["requests_scored"] != requests:
            raise RuntimeError(
                f"candidate {candidate['candidate_id']} did not score every request"
            )
        metrics = candidate_metrics(
            devices,
            config["safety_rates"],
            config["effectiveness_targets"],
        )
        if metrics["attacker_review_or_higher"]["denominator"] != 300:
            raise RuntimeError("confirmation attacker denominator changed")
        record = {"candidate": candidate, "metrics": metrics, "audit": audit}
        candidate_records.append(record)
        result_rows.append(_candidate_row(candidate, metrics, audit))
    replay_seconds = time.perf_counter() - replay_started
    feasible = [row for row in candidate_records if row["metrics"]["feasible"]]
    feasible.sort(key=lambda row: selection_key(row["candidate"], row["metrics"]))
    champion = feasible[0] if feasible else None
    _write_csv(
        pd.DataFrame(result_rows).sort_values("candidate_id"),
        output / "candidate_results.csv",
    )
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
        if (
            len(decisions) != requests
            or decisions.event_id.nunique() != requests
            or decisions.raw_probability.isna().any()
            or decisions.calibrated_probability.isna().any()
            or decisions.action.eq("counterfactual_after_block").any()
        ):
            raise RuntimeError("champion did not score every raw authorization request")
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
            "decision_rows": int(len(decisions)),
            "counterfactual_after_block_rows": 0,
        }
        if not reproduction["passed"]:
            raise RuntimeError("confirmation champion did not reproduce exactly")
        _write_csv(decisions, output / "champion_decisions.csv")
        _write_csv(devices, output / "champion_device_summary.csv")
        original_freeze = json.loads(
            (root / "artifacts/v2/phase2c/freeze/development_freeze.json").read_text()
        )
        frozen_policy = {
            "version": "v2-phase2c-operational-policy-1",
            "selected_utc": datetime.now(UTC).isoformat(),
            "policy": champion["candidate"],
            "metrics": champion["metrics"],
            "reason_code_contract": original_freeze["reason_code_contract"],
            "state_schema_version": original_freeze["state_schema_version"],
            "model_contract": original_freeze["model_contract"],
            "original_development_freeze_sha256": correction["invalidation"][
                "invalidated_freeze_sha256"
            ],
            "effective_replacement_freeze_sha256": correction[
                "replacement_freeze_sha256"
            ],
            "execution_amendment_sha256": correction["execution_amendment_sha256"],
            "dataset_manifest_sha256": CONFIRMATION_MANIFEST_SHA256,
            "phase2b_policy_preserved": True,
            "blind_evaluated": False,
        }
        policy_path = output / "frozen_operational_policy.json"
        atomic_write_json(policy_path, frozen_policy)
        policy_digest = sha256_file(policy_path)
        atomic_write_text(
            output / "frozen_operational_policy.sha256", policy_digest + "\n"
        )
        phase2b_path = (
            root / "artifacts/v2/phase2b/validation/frozen_operational_policy.json"
        )
        phase2b_policy = json.loads(phase2b_path.read_text())
        comparison = {
            "phase2b": {
                "policy_sha256": sha256_file(phase2b_path),
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
        "candidate_count": 20,
        "feasible_candidate_count": len(feasible),
        "champion": champion,
        "reproduction": reproduction,
        "effective_replacement_freeze_sha256": correction["replacement_freeze_sha256"],
        "no_result_dependent_changes": True,
        "additional_confirmation_generation_authorized": False,
        "blind_evaluated": False,
    }
    atomic_write_json(output / "feasibility.json", feasibility)
    runtime = {
        "candidate_count": 20,
        "requests_per_candidate": requests,
        "candidate_requests": requests * 20,
        "causal_replay_seconds": replay_seconds,
        "candidate_requests_per_second": requests * 20 / replay_seconds,
        "total_seconds_before_manifest": time.perf_counter() - started,
        "frozen_model_loaded_once": True,
        "canonical_runtime": runtime_contract,
        "per_request_dataframes": False,
        "all_later_post_block_requests_scored": True,
        "deterministic_result_ordering": True,
    }
    atomic_write_json(output / "runtime.json", runtime)
    completion = {
        "version": "v2-phase2c-access-ledger-completion-001",
        "completed_utc": datetime.now(UTC).isoformat(),
        "original_access_ledger_sha256": ORIGINAL_LEDGER_SHA256,
        "ledger_amendment_sha256": correction["ledger_amendment_sha256"],
        "execution_amendment_sha256": correction["execution_amendment_sha256"],
        "effective_replacement_freeze_sha256": correction["replacement_freeze_sha256"],
        "scoring_attempt": 1,
        "resume_of_existing_attempt": True,
        "second_independent_evaluation": False,
        "status": status,
        "candidates_evaluated": 20,
        "requests_scored_per_candidate": requests,
        "feasible_candidate_count": len(feasible),
        "frozen_operational_policy_sha256": policy_digest,
    }
    completion_digest = _write_completion(root / LEDGER_COMPLETION_PATH, completion)
    protected = [
        str(REPLACEMENT_FREEZE_PATH),
        str(CONFIRMATION_RELATIVE_PATH / "manifest.json"),
        str(EVALUATION_RELATIVE_PATH / "access_ledger.json"),
        str(LEDGER_AMENDMENT_PATH),
        str(LEDGER_COMPLETION_PATH),
        str(LEDGER_COMPLETION_PATH.with_suffix(".sha256")),
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
        "# Phase 2C corrected one-time confirmation evaluation",
        "",
        f"- Status: {status}",
        "- Logical scoring attempt: 1 (resumed; not a second evaluation)",
        "- Frozen candidates evaluated: 20/20",
        f"- Feasible candidates: {len(feasible)}",
        f"- Champion: {champion['candidate']['candidate_id'] if champion else 'none'}",
        f"- Requests scored per candidate: {requests}",
        f"- Candidate-requests/second: {runtime['candidate_requests_per_second']:.2f}",
        "- Post-block later requests feature-computed and scored: yes",
        "- Blind data accessed: no",
    ]
    atomic_write_text(
        root / "reports/v2/phase2c/confirmation_evaluation.md",
        "\n".join(report) + "\n",
    )
    verify_resumed_post_scoring(root)
    return {
        "status": status,
        "candidate_count": 20,
        "feasible_candidate_count": len(feasible),
        "champion": champion,
        "operational_policy_sha256": policy_digest,
        "ledger_completion_sha256": completion_digest,
        "final_manifest_sha256": manifest_digest,
        "runtime": runtime,
        "dataset": dataset,
    }
