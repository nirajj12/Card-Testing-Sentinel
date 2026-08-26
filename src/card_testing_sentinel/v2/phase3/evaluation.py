"""Exactly-once evaluation of the frozen Phase 2C policy on blind data."""

from __future__ import annotations

import json
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from card_testing_sentinel.common.atomic_io import atomic_write_json, atomic_write_text
from card_testing_sentinel.v2.evaluation.metrics import probability_metrics
from card_testing_sentinel.v2.phase2b.validation_policy import (
    OptimizedFrozenScorer,
    verify_allow_all_parity,
)
from card_testing_sentinel.v2.phase2c.replay import (
    candidate_metrics,
    replay_stateful_candidate,
)
from card_testing_sentinel.v2.phase3.contracts import (
    ARTIFACT_PATH,
    DATA_PATH,
    DATASET_MANIFEST_PATH,
    FINAL_STATUSES,
    FREEZE_PATH,
    LEDGER_PATH,
    POLICY_ID,
    POLICY_SHA256,
    REPORT_PATH,
    ROOT,
)
from card_testing_sentinel.v2.phase3.lifecycle import (
    accept_scoring_once,
    complete_scoring_ledger,
    load_blind_config,
    refuse_if_scoring_accessed,
    sha256_file,
    verify_dataset_manifest,
    verify_lifecycle,
    verify_pre_access_freeze,
)


class TimedScorer:
    """Record numeric scoring latency without altering the frozen scorer."""

    def __init__(self, scorer: OptimizedFrozenScorer):
        self.scorer = scorer
        self.latencies_ns: list[int] = []

    def score_snapshot(self, snapshot: dict) -> tuple[float, float]:
        started = time.perf_counter_ns()
        result = self.scorer.score_snapshot(snapshot)
        self.latencies_ns.append(time.perf_counter_ns() - started)
        return result


def load_frozen_policy(root: Path = ROOT) -> dict:
    path = root / "artifacts/v2/phase2c/confirmation/frozen_operational_policy.json"
    if sha256_file(path) != POLICY_SHA256:
        raise PermissionError("frozen Phase 2C policy hash drift")
    payload = json.loads(path.read_text())
    policy = payload["policy"]
    if policy.get("candidate_id") != POLICY_ID:
        raise PermissionError("the blind policy is not phase2c_002")
    return policy


def result_status(metrics: dict, integrity_passed: bool = True) -> str:
    if not integrity_passed:
        return "blind_execution_failed"
    status = (
        "blind_completed_passed"
        if metrics["safety_passed"] and metrics["effectiveness_passed"]
        else "blind_completed_failed"
    )
    if status not in FINAL_STATUSES:
        raise RuntimeError("uncontracted Phase 3 status")
    return status


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    atomic_write_text(
        path,
        frame.to_csv(index=False, lineterminator="\n", float_format="%.12g"),
    )


def _distribution(values: pd.Series) -> dict:
    values = values.dropna().astype(float)
    return {
        "count": int(len(values)),
        "median": float(values.median()) if len(values) else None,
        "mean": float(values.mean()) if len(values) else None,
        "p90": float(values.quantile(0.9)) if len(values) else None,
    }


def _latency_summary(latencies_ns: list[int]) -> dict:
    values = np.asarray(latencies_ns, dtype=float) / 1_000_000.0
    if not len(values):
        raise RuntimeError("no per-request scoring latencies were recorded")
    return {
        "unit": "milliseconds",
        "p50": float(np.quantile(values, 0.50)),
        "p95": float(np.quantile(values, 0.95)),
        "p99": float(np.quantile(values, 0.99)),
        "maximum": float(values.max()),
    }


def _extended_policy_metrics(
    raw: pd.DataFrame, decisions: pd.DataFrame, devices: pd.DataFrame
) -> dict:
    requests = raw.loc[
        raw.event_type.eq("authorization_request"),
        [
            "event_id",
            "card_fingerprint",
        ],
    ]
    joined = decisions.merge(requests, on="event_id", validate="one_to_one")
    first_review = devices.set_index("device_id")["first_review_or_higher_request"]
    first_block = devices.set_index("device_id")["first_block_request"]
    joined["first_review_index"] = joined.device_id.map(first_review)
    joined["first_block_index"] = joined.device_id.map(first_block)
    reviewed_ids = set(devices.loc[devices.review_or_higher, "device_id"])
    blocked_ids = set(devices.loc[devices.blocked, "device_id"])
    through_review = joined.loc[
        joined.device_id.isin(reviewed_ids)
        & joined.request_index.le(joined.first_review_index)
    ]
    before_review = joined.loc[joined.request_index.lt(joined.first_review_index)]
    through_block = joined.loc[
        joined.device_id.isin(blocked_ids)
        & joined.request_index.le(joined.first_block_index)
    ]
    before_block = joined.loc[joined.request_index.lt(joined.first_block_index)]
    reviewed = devices.loc[devices.review_or_higher]
    blocked = devices.loc[devices.blocked]
    later_after_review = int(
        (
            devices.request_index
            - devices.first_review_or_higher_request.fillna(devices.request_index)
        ).sum()
    )
    later_after_block = int(
        (
            devices.request_index
            - devices.first_block_request.fillna(devices.request_index)
        ).sum()
    )
    return {
        "attempts_processed_before_first_review": _distribution(
            reviewed.authorizations_processed_before_first_action
        ),
        "attempts_scored_through_first_review": _distribution(
            reviewed.requests_scored_through_first_action
        ),
        "attempts_processed_before_first_block": _distribution(
            blocked.first_block_request - 1
        ),
        "attempts_scored_through_first_block": _distribution(
            blocked.first_block_request
        ),
        "distinct_cards_before_first_review": _distribution(
            before_review.groupby("device_id").card_fingerprint.nunique()
        ),
        "distinct_cards_through_first_review": _distribution(
            through_review.groupby("device_id").card_fingerprint.nunique()
        ),
        "distinct_cards_before_first_block": _distribution(
            before_block.groupby("device_id").card_fingerprint.nunique()
        ),
        "distinct_cards_through_first_block": _distribution(
            through_block.groupby("device_id").card_fingerprint.nunique()
        ),
        "seconds_to_first_review": _distribution(reviewed.seconds_to_first_review),
        "seconds_to_first_block": _distribution(blocked.seconds_to_first_block),
        "later_recorded_attempts_after_first_review": later_after_review,
        "later_recorded_attempts_after_first_block": later_after_block,
    }


def _model_diagnostics(decisions: pd.DataFrame) -> dict:
    labels = decisions.label.to_numpy(dtype=int)
    weights = np.ones(len(decisions), dtype=float)
    return {
        "scope": "authorization rows; unweighted audit diagnostics",
        "rows": int(len(decisions)),
        "raw": probability_metrics(
            labels, decisions.raw_probability.to_numpy(dtype=float), weights
        ),
        "calibrated": probability_metrics(
            labels, decisions.calibrated_probability.to_numpy(dtype=float), weights
        ),
    }


def _decision_frame(raw: pd.DataFrame, decisions: pd.DataFrame) -> pd.DataFrame:
    metadata = raw.loc[
        raw.event_type.eq("authorization_request"),
        [
            "event_id",
            "timestamp",
            "event_sequence",
            "session_id",
            "label",
            "population",
            "attack_subtype",
            "scenario_tag",
        ],
    ]
    merged = decisions.merge(metadata, on="event_id", validate="one_to_one")
    if len(merged) != int(raw.event_type.eq("authorization_request").sum()):
        raise RuntimeError("not every blind authorization request received a decision")
    if merged[["raw_probability", "calibrated_probability"]].isna().any().any():
        raise RuntimeError("blind scoring produced missing probability")
    return merged.sort_values(["timestamp", "event_sequence"], kind="mergesort")


def _render_report(metrics: dict, runtime: dict, manifest_hash: str | None) -> str:
    safety = metrics["operational_policy"]["budget_results"]
    subtype = metrics["operational_policy"]["subtype"]
    lines = [
        "# Phase 3 final blind challenge closeout",
        "",
        f"- Status: `{metrics['status']}`",
        f"- Seed: `{metrics['dataset_integrity']['seed']}`",
        f"- Frozen policy: `{POLICY_ID}`",
        "- Policies evaluated: `1`",
        "- No retraining, refitting, retuning, regeneration, or candidate search",
        "",
        "## Safety",
        "",
        "| Population | Review-or-higher | Allowance | Blocks | Allowance | Pass |",
        "|---|---:|---:|---:|---:|:---:|",
    ]
    for name, row in safety.items():
        lines.append(
            f"| {name} | {row['review_or_higher_devices']}/"
            f"{row['denominator_devices']} | {row['review_allowance_devices']} | "
            f"{row['block_devices']} | {row['block_allowance_devices']} | "
            f"{'yes' if row['passed'] else 'no'} |"
        )
    lines.extend(
        [
            "",
            "## Effectiveness",
            "",
            "| Attacker group | Review-or-higher | Blocks | Never detected |",
            "|---|---:|---:|---:|",
        ]
    )
    for name, row in subtype.items():
        review = row["review_or_higher"]
        block = row["block"]
        lines.append(
            f"| {name} | {review['numerator']}/{review['denominator']} | "
            f"{block['numerator']}/{block['denominator']} | "
            f"{row['never_detected']} |"
        )
    lines.extend(
        [
            "",
            "## Integrity and runtime",
            "",
            f"- Dataset manifest: `{metrics['dataset_manifest_sha256']}`",
            f"- Online/batch maximum difference: "
            f"`{metrics['online_batch_parity']['feature_parity']['maximum_absolute_difference']}`",
            f"- Requests scored: `{runtime['total_requests_scored']}`",
            f"- Replay seconds: `{runtime['single_policy_replay_seconds']:.6f}`",
            f"- Requests/second: `{runtime['requests_per_second']:.2f}`",
            f"- Final manifest: `{manifest_hash or 'written after report'}`",
            "",
            "Potentially preventable attempts are an **offline replay upper bound—"
            "not observed or causal fraud prevention**.",
        ]
    )
    return "\n".join(lines) + "\n"


def _write_final_manifest(root: Path, paths: list[Path]) -> str:
    output = root / ARTIFACT_PATH
    manifest_path = output / "final_hash_manifest.json"
    payload = {
        "version": "v2-phase3-final-hash-manifest-1",
        "created_utc": datetime.now(UTC).isoformat(),
        "protected_hashes": {
            str(path): sha256_file(root / path) for path in sorted(paths)
        },
        "policies_evaluated": 1,
    }
    atomic_write_json(manifest_path, payload)
    digest = sha256_file(manifest_path)
    atomic_write_text(manifest_path.with_suffix(".sha256"), digest + "\n")
    return digest


def verify_final_manifest(root: Path = ROOT) -> dict:
    path = root / ARTIFACT_PATH / "final_hash_manifest.json"
    digest_path = path.with_suffix(".sha256")
    if not path.is_file() or not digest_path.is_file():
        raise FileNotFoundError("blind final manifest is incomplete")
    if sha256_file(path) != digest_path.read_text().strip():
        raise PermissionError("blind final manifest digest drift")
    payload = json.loads(path.read_text())
    if payload.get("policies_evaluated") != 1:
        raise PermissionError("blind final manifest policy count drift")
    for relative, digest in payload["protected_hashes"].items():
        candidate = root / relative
        if not candidate.is_file() or sha256_file(candidate) != digest:
            raise PermissionError(f"blind final result drift: {relative}")
    return payload


def run_blind_once(root: Path = ROOT) -> dict:
    """Evaluate one frozen policy once; refuse before data read on later calls."""
    refuse_if_scoring_accessed(root)
    verify_pre_access_freeze(root)
    verify_lifecycle(root, "post_generation_pre_scoring")
    config = load_blind_config(root)
    manifest = verify_dataset_manifest(root)

    load_started = time.perf_counter()
    artifact = joblib.load(
        root / "artifacts/v2/phase2b/training/models/selected_model.joblib"
    )
    scorer = OptimizedFrozenScorer(artifact)
    policy = load_frozen_policy(root)
    artifact_load_seconds = time.perf_counter() - load_started

    raw = pd.read_csv(root / DATA_PATH / "raw_events.csv")
    contract = pd.read_csv(root / DATA_PATH / "device_contract.csv")
    parity_started = time.perf_counter()
    allow_all, feature_parity = verify_allow_all_parity(
        raw, float(config["parity_tolerance"])
    )
    probability_parity = scorer.verify_parity(
        allow_all.head(512), float(config["parity_tolerance"])
    )
    parity_seconds = time.perf_counter() - parity_started
    parity = {
        "feature_parity": feature_parity,
        "optimized_probability_parity": probability_parity,
        "frozen_model_and_calibrator_loaded_once": True,
    }
    atomic_write_json(root / ARTIFACT_PATH / "allow_all_parity.json", parity)

    accepted_started = time.perf_counter()
    accept_scoring_once(root)
    timed_scorer = TimedScorer(scorer)
    try:
        replay_started = time.perf_counter()
        decisions, devices, audit = replay_stateful_candidate(
            raw, contract, timed_scorer, policy, capture_decisions=True
        )
        replay_seconds = time.perf_counter() - replay_started
        decisions = _decision_frame(raw, decisions)
        if audit["requests_scored"] != audit["requests_generated"]:
            raise RuntimeError("blind replay did not score every authorization request")
        operational = candidate_metrics(
            devices,
            config["safety_rates"],
            config["effectiveness_targets"],
        )
        status = result_status(operational)
        action_counts = dict(sorted(Counter(decisions.action).items()))
        diagnostics = _model_diagnostics(decisions)
        extended = _extended_policy_metrics(raw, decisions, devices)
        runtime = {
            "artifact_load_seconds": artifact_load_seconds,
            "dataset_generation_seconds": manifest["generation_runtime"][
                "dataset_generation_seconds"
            ],
            "dataset_validation_seconds": manifest["generation_runtime"][
                "dataset_validation_seconds"
            ],
            "allow_all_parity_seconds": parity_seconds,
            "single_policy_replay_seconds": replay_seconds,
            "total_accepted_evaluation_seconds": time.perf_counter() - accepted_started,
            "requests_per_second": audit["requests_scored"] / replay_seconds,
            "per_request_scoring_latency": _latency_summary(timed_scorer.latencies_ns),
            "artifact_loads": 1,
            "per_request_dataframe_constructions": 0,
            "total_requests_scored": audit["requests_scored"],
            "total_policies_evaluated": 1,
        }
        metrics = {
            "version": "v2-phase3-final-blind-metrics-1",
            "status": status,
            "policy_id": POLICY_ID,
            "policy_sha256": POLICY_SHA256,
            "policies_evaluated": 1,
            "dataset_manifest_sha256": sha256_file(root / DATASET_MANIFEST_PATH),
            "dataset_integrity": manifest["structural_validation"],
            "generation_determinism": manifest["determinism_evidence"],
            "online_batch_parity": parity,
            "model_diagnostics": diagnostics,
            "operational_policy": operational,
            "extended_operational_metrics": extended,
            "action_counts": action_counts,
            "audit": {
                **audit,
                "current_request_outcome_leakage": False,
                "post_block_later_requests_scored": True,
                "every_raw_authorization_received_one_decision": True,
                "attacker_denominator_includes_never_detected": True,
                "potentially_preventable_label": (
                    "offline replay upper bound—not observed or causal fraud prevention"
                ),
                "confirmation_detected_within_three_attempts": 0,
                "blind_detected_within_three_attempts": operational["within_attempt"][
                    "3"
                ]["review_or_higher"],
                "early_detection_limitation": (
                    "confirmed"
                    if operational["within_attempt"]["3"]["review_or_higher"] == 0
                    else "contradicted"
                ),
            },
        }
        output = root / ARTIFACT_PATH
        atomic_write_json(output / "final_blind_metrics.json", metrics)
        _write_csv(decisions, output / "final_blind_event_decisions.csv")
        _write_csv(devices, output / "final_blind_device_summary.csv")
        atomic_write_json(output / "runtime.json", runtime)
        report = _render_report(metrics, runtime, None)
        atomic_write_text(root / REPORT_PATH, report)
        hashed_outputs = {
            str(path): sha256_file(root / path)
            for path in (
                ARTIFACT_PATH / "allow_all_parity.json",
                ARTIFACT_PATH / "final_blind_metrics.json",
                ARTIFACT_PATH / "final_blind_event_decisions.csv",
                ARTIFACT_PATH / "final_blind_device_summary.csv",
                ARTIFACT_PATH / "runtime.json",
                REPORT_PATH,
            )
        }
        complete_scoring_ledger(root, status, hashed_outputs)
        manifest_paths = [
            FREEZE_PATH,
            FREEZE_PATH.with_suffix(".sha256"),
            DATASET_MANIFEST_PATH,
            LEDGER_PATH,
            ARTIFACT_PATH / "allow_all_parity.json",
            ARTIFACT_PATH / "final_blind_metrics.json",
            ARTIFACT_PATH / "final_blind_event_decisions.csv",
            ARTIFACT_PATH / "final_blind_device_summary.csv",
            ARTIFACT_PATH / "runtime.json",
            REPORT_PATH,
        ]
        final_manifest_sha256 = _write_final_manifest(root, manifest_paths)
        verify_final_manifest(root)
        verify_lifecycle(root, "post_scoring")
    except BaseException:
        ledger_path = root / LEDGER_PATH
        if ledger_path.is_file():
            ledger = json.loads(ledger_path.read_text())
            if ledger.get("current_state") != "post_scoring":
                ledger["result_status"] = "blind_execution_failed"
                atomic_write_json(ledger_path, ledger)
        raise
    return {
        "status": status,
        "metrics": metrics,
        "runtime": runtime,
        "final_manifest_sha256": final_manifest_sha256,
    }
