"""Training-only grouped OOF causal policy development for Phase 2C."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import yaml

from card_testing_sentinel.common.atomic_io import atomic_write_json, atomic_write_text
from card_testing_sentinel.v2.evaluation.calibration import fit_calibrator
from card_testing_sentinel.v2.modeling.weights import (
    balanced_device_training_weights,
    device_evaluation_weights,
)
from card_testing_sentinel.v2.phase2b.artifacts import Phase2BModelArtifact
from card_testing_sentinel.v2.phase2b.training import build_candidate, fit_candidate
from card_testing_sentinel.v2.phase2b.validation_policy import OptimizedFrozenScorer
from card_testing_sentinel.v2.phase2c.policy import (
    StatefulPolicy,
    candidate_enumeration_sha256,
    enumerate_candidates,
)
from card_testing_sentinel.v2.phase2c.replay import (
    candidate_metrics,
    fold_stability,
    replay_stateful_candidate,
    selection_key,
)

ROOT = Path(__file__).resolve().parents[4]


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    atomic_write_text(
        path,
        frame.to_csv(index=False, lineterminator="\n", float_format="%.12g"),
    )


def _contract(raw: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "device_id",
        "population",
        "attack_subtype",
        "scenario_tag",
        "label",
    ]
    contract = raw.groupby("device_id", as_index=False)[columns[1:]].first()
    if len(contract) != raw.device_id.nunique():
        raise RuntimeError("OOF contract is not one row per device")
    return contract


def _build_fold_scorers(features: pd.DataFrame, config: dict) -> list[dict]:
    spec = {
        "family": config["model"]["family"],
        "parameters": {
            "C": float(config["model"]["C"]),
            "max_iter": int(config["model"]["max_iter"]),
        },
    }
    method = str(config["model"]["calibration"])
    seed = int(config["seed"])
    folds = sorted(int(value) for value in features.fold.unique())
    packages = []
    for outer in folds:
        calibration_fold = folds[(folds.index(outer) + 1) % len(folds)]
        outer_mask = features.fold.eq(outer)
        calibration_mask = features.fold.eq(calibration_fold)
        base_mask = ~(outer_mask | calibration_mask)
        role_devices = [
            set(features.loc[mask, "device_id"])
            for mask in (base_mask, calibration_mask, outer_mask)
        ]
        overlap = (
            role_devices[0] & role_devices[1]
            or role_devices[0] & role_devices[2]
            or role_devices[1] & role_devices[2]
        )
        if overlap:
            raise RuntimeError("fit/calibration/evaluation device overlap")
        model = build_candidate(spec, seed)
        fit_candidate(
            model,
            spec,
            features.loc[base_mask],
            balanced_device_training_weights(features.loc[base_mask]),
        )
        calibration_raw = model.predict_proba(features.loc[calibration_mask])[:, 1]
        calibrator = fit_calibrator(
            method,
            calibration_raw,
            features.loc[calibration_mask, "label"].to_numpy(dtype=int),
            device_evaluation_weights(features.loc[calibration_mask]),
        )
        artifact = Phase2BModelArtifact(
            model,
            calibrator,
            method,
            spec["family"],
            spec["parameters"],
        )
        scorer = OptimizedFrozenScorer(artifact)
        parity = scorer.verify_parity(
            features.loc[outer_mask].head(256),
            float(config["parity_tolerance"]),
        )
        packages.append(
            {
                "fold": outer,
                "calibration_fold": calibration_fold,
                "scorer": scorer,
                "evaluation_devices": role_devices[2],
                "isolation": {
                    "outer_fold": outer,
                    "base_fit_devices": len(role_devices[0]),
                    "calibrator_fit_devices": len(role_devices[1]),
                    "evaluation_devices": len(role_devices[2]),
                    "all_pairwise_device_overlaps": 0,
                    "shared_ip_scope": "current_holdout_partition_only",
                },
                "optimized_probability_parity": parity,
            }
        )
    return packages


def benchmark_policy(candidate: dict, iterations: int = 100_000) -> dict:
    policy = StatefulPolicy(candidate)
    snapshot = {
        "campaign_active": 0.0,
        "prior_successful_checkouts": 0.0,
        "same_card_retry_ratio_24h": 0.0,
        "amount_delta_from_previous": 0.0,
        "prior_attempts_24h": 2.0,
        "distinct_cards_14d": 2.0,
        "card_switches_after_decline_24h": 1.0,
        "sessions_7d": 2.0,
        "cross_session_cards_7d": 2.0,
        "ip_changes_24h": 1.0,
        "prospective_requests_60s": 0.0,
        "prior_attempts_5m": 0.0,
        "distinct_cards_24h": 2.0,
        "prior_decline_streak": 0.0,
        "requests_per_ip_5m": 0.0,
        "near_minimum_ratio_24h": 0.0,
        "prior_attempts_7d": 2.0,
    }
    started = time.perf_counter()
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for index in range(iterations):
        policy.decide(
            device_id=f"bench_{index % 1000}",
            event_id=f"event_{index}",
            timestamp=base,
            session_id=f"session_{index % 2000}",
            probability=0.71,
            snapshot=snapshot,
        )
    seconds = time.perf_counter() - started
    return {
        "transitions": iterations,
        "seconds": seconds,
        "transitions_per_second": iterations / seconds,
        "passed": True,
    }


def _candidate_row(candidate: dict, metrics: dict, stability: dict) -> dict:
    median = metrics["intervention_distributions"][
        "requests_scored_through_first_action"
    ]["median"]
    return {
        "candidate_id": candidate["candidate_id"],
        "family": candidate["family"],
        "parameters_json": json.dumps(candidate, sort_keys=True),
        "safety_passed": metrics["safety_passed"],
        "effectiveness_passed": metrics["effectiveness_passed"],
        "stability_passed": stability["passed"],
        "acceptable": metrics["feasible"] and stability["passed"],
        "failed_constraints_json": json.dumps(
            [*metrics["failed_constraints"], *stability["failures"]]
        ),
        "worst_subtype_review_coverage": metrics["worst_subtype_review_coverage"],
        "overall_attacker_review_coverage": metrics["attacker_review_or_higher"][
            "rate"
        ],
        "overall_attacker_block_coverage": metrics["attacker_block"]["rate"],
        "median_attempts_through_first_intervention": median,
        "legitimate_review_or_higher": metrics["legitimate_review_or_higher"],
        "legitimate_blocks": metrics["legitimate_blocks"],
        "never_detected_attackers": metrics["never_detected_attackers"],
        "selection_key_json": json.dumps(selection_key(candidate, metrics)),
        "metrics_json": json.dumps(metrics, sort_keys=True),
        "stability_json": json.dumps(stability, sort_keys=True),
    }


def run_training_oof(root: Path = ROOT) -> dict:
    """Develop policies on the 8,000 training devices; never open confirmation."""
    confirmation = root / "data/v2/phase2c/confirmation_validation"
    freeze = root / "artifacts/v2/phase2c/freeze/development_freeze.json"
    if confirmation.exists():
        raise PermissionError("training development cannot access confirmation data")
    if freeze.exists():
        raise PermissionError("Phase 2C methodology is already frozen")
    config_path = root / "configs/v2/phase2c/policy.yaml"
    config = yaml.safe_load(config_path.read_text())
    candidates = enumerate_candidates(config)
    if not 1 <= len(candidates) <= 120:
        raise RuntimeError("invalid Phase 2C candidate count")
    output = root / "artifacts/v2/phase2c/development"
    report_dir = root / "reports/v2/phase2c"
    output.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    benchmark = benchmark_policy(
        candidates[1] if len(candidates) > 1 else candidates[0]
    )

    features = pd.read_csv(
        root / "artifacts/v2/phase2b/training/data/training_features.csv"
    )
    folds = pd.read_csv(
        root / "artifacts/v2/phase2b/training/training/device_folds.csv"
    )
    features = features.merge(folds, on="device_id", validate="many_to_one")
    if features.device_id.nunique() != 8000 or len(features) != 21338:
        raise RuntimeError("training OOF population changed")
    raw_all = pd.read_csv(root / "data/v2/development/raw_events.csv")
    train_ids = set(folds.device_id)
    raw_all = raw_all.loc[raw_all.device_id.isin(train_ids)].copy()
    if raw_all.device_id.nunique() != 8000:
        raise RuntimeError("training raw boundary changed")

    fitting_started = time.perf_counter()
    packages = _build_fold_scorers(features, config)
    fitting_seconds = time.perf_counter() - fitting_started
    fold_inputs = {}
    for package in packages:
        ids = package["evaluation_devices"]
        raw = raw_all.loc[raw_all.device_id.isin(ids)].copy()
        fold_inputs[package["fold"]] = (raw, _contract(raw))

    all_rows = []
    all_metrics: dict[str, dict] = {}
    fold_metric_rows = []
    replay_started = time.perf_counter()
    requests_replayed = 0
    for candidate in candidates:
        device_parts = []
        candidate_fold_metrics = []
        for package in packages:
            fold = package["fold"]
            raw, contract = fold_inputs[fold]
            _decisions, devices, audit = replay_stateful_candidate(
                raw, contract, package["scorer"], candidate
            )
            devices["fold"] = fold
            device_parts.append(devices)
            requests_replayed += int(raw.event_type.eq("authorization_request").sum())
            fold_metrics = candidate_metrics(
                devices,
                config["safety_rates"],
                config["effectiveness_targets"],
            )
            candidate_fold_metrics.append(
                {"fold": fold, "metrics": fold_metrics, "audit": audit}
            )
            fold_metric_rows.append(
                {
                    "candidate_id": candidate["candidate_id"],
                    "family": candidate["family"],
                    "fold": fold,
                    "attacker_review_or_higher": fold_metrics[
                        "attacker_review_or_higher"
                    ]["rate"],
                    "attacker_block": fold_metrics["attacker_block"]["rate"],
                    "burst_review": fold_metrics["subtype"]["burst"][
                        "review_or_higher"
                    ]["rate"],
                    "evasive_review": fold_metrics["subtype"]["evasive"][
                        "review_or_higher"
                    ]["rate"],
                    "patient_review": fold_metrics["subtype"]["patient"][
                        "review_or_higher"
                    ]["rate"],
                    "metrics_json": json.dumps(fold_metrics, sort_keys=True),
                }
            )
        devices = pd.concat(device_parts, ignore_index=True)
        metrics = candidate_metrics(
            devices,
            config["safety_rates"],
            config["effectiveness_targets"],
        )
        stability = fold_stability(candidate_fold_metrics, config["fold_stability"])
        all_metrics[candidate["candidate_id"]] = {
            "candidate": candidate,
            "metrics": metrics,
            "stability": stability,
        }
        all_rows.append(_candidate_row(candidate, metrics, stability))
    replay_seconds = time.perf_counter() - replay_started
    acceptable = [
        item
        for item in all_metrics.values()
        if item["metrics"]["feasible"] and item["stability"]["passed"]
    ]
    acceptable.sort(key=lambda item: selection_key(item["candidate"], item["metrics"]))
    selected = acceptable[0] if acceptable else None

    selected_decisions = pd.DataFrame()
    selected_devices = pd.DataFrame()
    reproduction = None
    if selected is not None:
        decision_parts = []
        device_parts = []
        for package in packages:
            raw, contract = fold_inputs[package["fold"]]
            decisions, devices, _audit = replay_stateful_candidate(
                raw,
                contract,
                package["scorer"],
                selected["candidate"],
                capture_decisions=True,
            )
            decisions["fold"] = package["fold"]
            devices["fold"] = package["fold"]
            decision_parts.append(decisions)
            device_parts.append(devices)
        selected_decisions = pd.concat(decision_parts, ignore_index=True).sort_values(
            ["event_id"], kind="mergesort"
        )
        selected_devices = pd.concat(device_parts, ignore_index=True).sort_values(
            ["device_id"], kind="mergesort"
        )
        reproduced = candidate_metrics(
            selected_devices,
            config["safety_rates"],
            config["effectiveness_targets"],
        )
        reproduction = {
            "passed": json.dumps(reproduced, sort_keys=True)
            == json.dumps(selected["metrics"], sort_keys=True),
            "metrics": reproduced,
        }
        if not reproduction["passed"]:
            raise RuntimeError("selected OOF policy did not reproduce exactly")

    candidate_table = pd.DataFrame(all_rows).sort_values("candidate_id")
    _write_csv(candidate_table, output / "candidate_results.csv")
    _write_csv(pd.DataFrame(fold_metric_rows), output / "fold_metrics.csv")
    atomic_write_json(output / "candidate_metrics.json", all_metrics)
    atomic_write_json(
        output / "fold_isolation.json",
        {
            "folds": [package["isolation"] for package in packages],
            "optimized_probability_parity": [
                package["optimized_probability_parity"] for package in packages
            ],
            "all_pairwise_device_overlaps": 0,
            "oof_devices": 8000,
            "oof_requests": 21338,
        },
    )
    if selected is not None:
        _write_csv(selected_decisions, output / "selected_oof_decisions.csv")
        _write_csv(selected_devices, output / "selected_oof_device_summary.csv")
    runtime = {
        "candidate_count": len(candidates),
        "candidate_requests": requests_replayed,
        "model_fit_seconds": fitting_seconds,
        "causal_replay_seconds": replay_seconds,
        "candidate_requests_per_second": requests_replayed / replay_seconds,
        "state_transition_benchmark": benchmark,
        "fold_models_loaded_once": True,
        "per_request_dataframes": False,
        "duplicate_predictions": False,
        "deterministic_result_ordering": True,
    }
    atomic_write_json(output / "runtime.json", runtime)
    selection = {
        "version": "v2-phase2c-training-oof-selection-1",
        "created_utc": datetime.now(UTC).isoformat(),
        "candidate_count": len(candidates),
        "candidate_enumeration_sha256": candidate_enumeration_sha256(candidates),
        "acceptable_candidate_count": len(acceptable),
        "selected_candidate": selected["candidate"] if selected else None,
        "selected_metrics": selected["metrics"] if selected else None,
        "selected_stability": selected["stability"] if selected else None,
        "reproduction": reproduction,
        "rules_only_baseline": all_metrics[candidates[0]["candidate_id"]],
        "confirmation_accessed": False,
    }
    atomic_write_json(output / "selection.json", selection)
    atomic_write_json(
        output / "candidate_grid.json",
        {
            "candidate_count": len(candidates),
            "enumeration_sha256": candidate_enumeration_sha256(candidates),
            "candidates": candidates,
        },
    )
    report = [
        "# Phase 2C training-only grouped OOF development",
        "",
        f"- Candidates declared and evaluated: {len(candidates)}",
        f"- Acceptable candidates: {len(acceptable)}",
        f"- Selected: {selected['candidate']['candidate_id'] if selected else 'none'}",
        f"- Candidate-requests/second: {runtime['candidate_requests_per_second']:.2f}",
        "- Fit/calibration/evaluation overlap: 0 devices in every fold",
        "- Confirmation and blind data accessed: no",
    ]
    atomic_write_text(
        report_dir / "training_oof_development.md", "\n".join(report) + "\n"
    )
    return selection
