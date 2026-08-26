"""Optimized one-time fresh-validation scoring and sequential policy replay."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from scipy.special import expit

from card_testing_sentinel.common.atomic_io import atomic_write_json, atomic_write_text
from card_testing_sentinel.v2.evaluation.metrics import (
    probability_metrics,
    reliability_table,
)
from card_testing_sentinel.v2.modeling.weights import device_evaluation_weights
from card_testing_sentinel.v2.phase2b.batch import (
    lifecycle_event,
    replay_training_events,
)
from card_testing_sentinel.v2.phase2b.engine import Phase2BFeatureEngine
from card_testing_sentinel.v2.phase2b.features import MODEL_FEATURE_COLUMNS
from card_testing_sentinel.v2.phase2b.fresh_validation import (
    FRESH_RELATIVE_PATH,
    open_fresh_validation_once,
    sha256_file,
)
from card_testing_sentinel.v2.policy.rules import evaluate_rules
from card_testing_sentinel.v2.policy.selection import choose_action, comparison_tuple


def _csv(frame: pd.DataFrame) -> str:
    return frame.to_csv(index=False, lineterminator="\n", float_format="%.12g")


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    atomic_write_text(path, _csv(frame))


class OptimizedFrozenScorer:
    """Exact numeric-array path for the frozen LR plus isotonic artifact."""

    def __init__(self, artifact):
        self.artifact = artifact
        model = artifact.base_model
        numeric = model.named_steps["preprocessing"].named_transformers_["numeric"]
        self.imputer = np.asarray(
            numeric.named_steps["imputer"].statistics_, dtype=float
        )
        scaler = numeric.named_steps["scaler"]
        self.mean = np.asarray(scaler.mean_, dtype=float)
        self.scale = np.asarray(scaler.scale_, dtype=float)
        classifier = model.named_steps["classifier"]
        self.coefficients = np.asarray(classifier.coef_[0], dtype=float)
        self.intercept = float(classifier.intercept_[0])
        self.calibration_method = artifact.calibration_method
        if self.calibration_method == "isotonic":
            self.iso_x = np.asarray(artifact.calibrator.X_thresholds_, dtype=float)
            self.iso_y = np.asarray(artifact.calibrator.y_thresholds_, dtype=float)

    def score_array(self, values: np.ndarray) -> tuple[float, float]:
        values = np.asarray(values, dtype=float)
        values = np.where(np.isnan(values), self.imputer, values)
        raw = float(
            expit(
                np.dot((values - self.mean) / self.scale, self.coefficients)
                + self.intercept
            )
        )
        if self.calibration_method == "none":
            return raw, raw
        if self.calibration_method == "sigmoid":
            calibrated = float(
                self.artifact.calibrator.predict_proba(np.asarray([[raw]]))[:, 1][0]
            )
        else:
            calibrated = float(np.interp(raw, self.iso_x, self.iso_y))
        return raw, calibrated

    def score_snapshot(self, snapshot: dict) -> tuple[float, float]:
        return self.score_array(
            np.fromiter(
                (snapshot[name] for name in MODEL_FEATURE_COLUMNS),
                dtype=float,
                count=len(MODEL_FEATURE_COLUMNS),
            )
        )

    def verify_parity(self, frame: pd.DataFrame, tolerance: float = 1e-12) -> dict:
        values = frame.loc[:, MODEL_FEATURE_COLUMNS].to_numpy(dtype=float)
        optimized = np.asarray([self.score_array(row) for row in values])
        expected_raw = self.artifact.predict_raw_proba(frame)
        expected_calibrated = self.artifact.predict_proba(frame)
        raw_maximum = float(np.max(np.abs(optimized[:, 0] - expected_raw), initial=0.0))
        calibrated_maximum = float(
            np.max(np.abs(optimized[:, 1] - expected_calibrated), initial=0.0)
        )
        maximum = max(raw_maximum, calibrated_maximum)
        if maximum > tolerance:
            raise RuntimeError(f"optimized frozen-score parity failed: {maximum}")
        return {
            "rows": len(frame),
            "raw_maximum_absolute_difference": raw_maximum,
            "calibrated_maximum_absolute_difference": calibrated_maximum,
            "maximum_absolute_difference": maximum,
            "tolerance": tolerance,
            "passed": True,
        }


def allow_all_replay(raw: pd.DataFrame) -> pd.DataFrame:
    """Direct online replay, used independently of the batch wrapper."""
    engine = Phase2BFeatureEngine()
    rows = []
    ordered = raw.sort_values(["timestamp", "event_sequence"], kind="mergesort")
    for record in ordered.to_dict("records"):
        event = lifecycle_event(record)
        if event.event_type == "authorization_request":
            snapshot = engine.precheck(event)
            rows.append(
                {
                    "event_id": event.event_id,
                    "request_id": event.request_id,
                    "timestamp": event.timestamp.isoformat(),
                    "device_id": event.device_id,
                    "session_id": event.session_id,
                    **{name: snapshot[name] for name in MODEL_FEATURE_COLUMNS},
                    "label": int(record["label"]),
                    "population": record["population"],
                    "attack_subtype": record.get("attack_subtype"),
                    "scenario_tag": record["scenario_tag"],
                }
            )
        elif event.event_type == "authorization_outcome":
            engine.record_outcome(event)
        else:
            engine.record_completion(event)
    return pd.DataFrame(rows)


def verify_allow_all_parity(raw: pd.DataFrame, tolerance: float = 1e-12):
    online = allow_all_replay(raw).sort_values("event_id").reset_index(drop=True)
    batch, _ = replay_training_events(raw)
    batch = batch.sort_values("event_id").reset_index(drop=True)
    if list(online.event_id) != list(batch.event_id):
        raise RuntimeError("allow-all online/batch request identity mismatch")
    differences = np.abs(
        online.loc[:, MODEL_FEATURE_COLUMNS].to_numpy(dtype=float)
        - batch.loc[:, MODEL_FEATURE_COLUMNS].to_numpy(dtype=float)
    )
    maximum = float(differences.max(initial=0.0))
    if maximum > tolerance:
        raise RuntimeError(f"allow-all feature parity failed: {maximum}")
    report = {
        "requests_scored": len(online),
        "feature_count": len(MODEL_FEATURE_COLUMNS),
        "maximum_absolute_difference": maximum,
        "tolerance": tolerance,
        "mismatched_rows": int((differences > tolerance).any(axis=1).sum()),
        "fresh_state": True,
        "passed": True,
    }
    return online, report


def _new_device_stats(contract: pd.DataFrame) -> dict[str, dict]:
    return {
        row.device_id: {
            "device_id": row.device_id,
            "label": int(row.label),
            "population": row.population,
            "attack_subtype": row.attack_subtype,
            "scenario_tag": row.scenario_tag,
            "request_index": 0,
            "first_request_time": None,
            "requested_cards": set(),
            "review_or_higher": False,
            "blocked": False,
            "first_action": "never",
            "first_review_or_higher_request": np.nan,
            "first_block_request": np.nan,
            "requests_scored_through_first_action": np.nan,
            "authorizations_processed_before_first_action": np.nan,
            "distinct_cards_requested_through_first_action": np.nan,
            "distinct_cards_processed_before_first_action": np.nan,
            "seconds_to_first_review": np.nan,
            "seconds_to_first_block": np.nan,
            "potentially_preventable_later_requests_upper_bound": 0,
        }
        for row in contract.itertuples(index=False)
    }


def replay_candidate(
    raw: pd.DataFrame,
    contract: pd.DataFrame,
    scorer: OptimizedFrozenScorer,
    candidate: dict,
    *,
    capture_decisions: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Replay one candidate from empty state with frozen permanent-block semantics."""
    engine = Phase2BFeatureEngine()
    stats = _new_device_stats(contract)
    blocked_devices: set[str] = set()
    blocked_requests: set[str] = set()
    decisions = []
    ordered = raw.sort_values(["timestamp", "event_sequence"], kind="mergesort")
    for record in ordered.to_dict("records"):
        event = lifecycle_event(record)
        state = stats[event.device_id]
        if event.device_id in blocked_devices:
            if event.event_type == "authorization_request":
                state["request_index"] += 1
                state["potentially_preventable_later_requests_upper_bound"] += 1
                if capture_decisions:
                    decisions.append(
                        {
                            "event_id": event.event_id,
                            "request_id": event.request_id,
                            "device_id": event.device_id,
                            "request_index": state["request_index"],
                            "action": "counterfactual_after_block",
                            "raw_probability": np.nan,
                            "calibrated_probability": np.nan,
                            "rule_score": np.nan,
                        }
                    )
            continue
        if event.event_type == "authorization_request":
            state["request_index"] += 1
            state["first_request_time"] = state["first_request_time"] or event.timestamp
            state["requested_cards"].add(event.card_fingerprint)
            device_state = engine.devices[event.device_id]
            processed_before = len(device_state.processed)
            processed_cards = {row.card_fingerprint for row in device_state.processed}
            phase1 = engine._snapshot(event, device_state)
            phase2b = engine._phase2b_snapshot(event)
            snapshot = {**phase1, **phase2b}
            raw_probability, probability = scorer.score_snapshot(snapshot)
            rule_score, reasons = evaluate_rules(snapshot)
            action = choose_action(candidate, probability, rule_score)
            committed = engine.precheck(
                event, blocked=action == "block_current_attempt"
            )
            if any(committed[name] != snapshot[name] for name in MODEL_FEATURE_COLUMNS):
                raise RuntimeError(
                    "policy decision was not based on immediate precheck state"
                )
            seconds = (event.timestamp - state["first_request_time"]).total_seconds()
            if (
                action in {"review", "block_current_attempt"}
                and not state["review_or_higher"]
            ):
                state.update(
                    {
                        "review_or_higher": True,
                        "first_action": action,
                        "first_review_or_higher_request": state["request_index"],
                        "requests_scored_through_first_action": state["request_index"],
                        "authorizations_processed_before_first_action": (
                            processed_before
                        ),
                        "distinct_cards_requested_through_first_action": len(
                            state["requested_cards"]
                        ),
                        "distinct_cards_processed_before_first_action": len(
                            processed_cards
                        ),
                        "seconds_to_first_review": seconds,
                    }
                )
            if action == "block_current_attempt":
                state["blocked"] = True
                state["first_block_request"] = state["request_index"]
                state["seconds_to_first_block"] = seconds
                blocked_devices.add(event.device_id)
                blocked_requests.add(event.request_id)
            if capture_decisions:
                decisions.append(
                    {
                        "event_id": event.event_id,
                        "request_id": event.request_id,
                        "device_id": event.device_id,
                        "request_index": state["request_index"],
                        "action": action,
                        "raw_probability": raw_probability,
                        "calibrated_probability": probability,
                        "rule_score": rule_score,
                        "reason_codes": "|".join(reasons),
                    }
                )
        elif event.event_type == "authorization_outcome":
            if event.request_id not in blocked_requests:
                engine.record_outcome(event)
        elif event.request_id not in blocked_requests:
            engine.record_completion(event)
    rows = []
    for state in stats.values():
        if np.isnan(state["requests_scored_through_first_action"]):
            state["requests_scored_through_first_action"] = state["request_index"]
            state["authorizations_processed_before_first_action"] = len(
                engine.devices[state["device_id"]].processed
            )
        row = {key: value for key, value in state.items() if key != "requested_cards"}
        rows.append(row)
    return pd.DataFrame(decisions), pd.DataFrame(rows)


def _rate(group: pd.DataFrame, column: str) -> dict:
    numerator = int(group[column].sum())
    denominator = int(len(group))
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate": numerator / denominator if denominator else None,
    }


def detailed_candidate_metrics(devices: pd.DataFrame, budgets: dict) -> dict:
    attackers = devices.loc[devices.label.eq(1)]
    legitimate = devices.loc[devices.label.eq(0)]
    budget_results = {}
    failed = []
    for name, budget in budgets.items():
        group = (
            legitimate
            if name == "overall_legitimate"
            else legitimate.loc[legitimate.scenario_tag.eq(name)]
        )
        review = int(group.review_or_higher.sum())
        block = int(group.blocked.sum())
        review_allowance = int(budget["review_or_higher_allowance"])
        block_allowance = int(budget["block_allowance"])
        row = {
            "denominator_devices": int(len(group)),
            "review_or_higher_devices": review,
            "review_only_devices": review - block,
            "block_devices": block,
            "review_allowance_devices": review_allowance,
            "block_allowance_devices": block_allowance,
            "review_excess_devices": max(0, review - review_allowance),
            "block_excess_devices": max(0, block - block_allowance),
            "passed": review <= review_allowance and block <= block_allowance,
        }
        if row["review_excess_devices"]:
            failed.append(
                f"{name}:review_excess={row['review_excess_devices']}_devices"
            )
        if row["block_excess_devices"]:
            failed.append(f"{name}:block_excess={row['block_excess_devices']}_devices")
        budget_results[name] = row
    subtype = {}
    for name, group in attackers.groupby("attack_subtype", sort=True):
        subtype[str(name)] = {
            "review_or_higher": _rate(group, "review_or_higher"),
            "block": _rate(group, "blocked"),
            "never_reviewed": int((~group.review_or_higher).sum()),
            "never_blocked": int((~group.blocked).sum()),
            "within_attempt": {
                str(limit): {
                    "review_or_higher": int(
                        group.first_review_or_higher_request.le(limit).sum()
                    ),
                    "block": int(group.first_block_request.le(limit).sum()),
                    "denominator": int(len(group)),
                }
                for limit in (1, 3, 5, 10)
            },
        }
    review_rates = [row["review_or_higher"]["rate"] for row in subtype.values()]
    block_rates = [row["block"]["rate"] for row in subtype.values()]
    acted = attackers.loc[attackers.review_or_higher]
    distributions = {}
    for column in (
        "requests_scored_through_first_action",
        "authorizations_processed_before_first_action",
        "distinct_cards_requested_through_first_action",
        "distinct_cards_processed_before_first_action",
        "seconds_to_first_review",
    ):
        values = acted[column].dropna()
        distributions[column] = {
            "count": int(len(values)),
            "median": float(values.median()) if len(values) else None,
            "mean": float(values.mean()) if len(values) else None,
            "p90": float(values.quantile(0.9)) if len(values) else None,
        }
    return {
        "feasible": not failed,
        "failed_constraints": failed,
        "budget_results": budget_results,
        "attacker_review_or_higher": _rate(attackers, "review_or_higher"),
        "attacker_block": _rate(attackers, "blocked"),
        "subtype": subtype,
        "worst_subtype_review_coverage": min(review_rates),
        "macro_subtype_review_coverage": float(np.mean(review_rates)),
        "worst_subtype_block_coverage": min(block_rates),
        "macro_subtype_block_coverage": float(np.mean(block_rates)),
        "median_processed_authorizations_before_first_action": float(
            acted.authorizations_processed_before_first_action.median()
        )
        if len(acted)
        else np.nan,
        "legitimate_review_or_higher": int(legitimate.review_or_higher.sum()),
        "legitimate_blocks": int(legitimate.blocked.sum()),
        "never_detected_attackers": int((~attackers.review_or_higher).sum()),
        "within_attempt": {
            str(limit): {
                "review_or_higher": int(
                    attackers.first_review_or_higher_request.le(limit).sum()
                ),
                "block": int(attackers.first_block_request.le(limit).sum()),
                "denominator": int(len(attackers)),
            }
            for limit in (1, 3, 5, 10)
        },
        "intervention_distributions": distributions,
        "potentially_preventable_later_attempts_offline_upper_bound": int(
            devices.potentially_preventable_later_requests_upper_bound.sum()
        ),
    }


def _candidate_row(candidate: dict, metrics: dict) -> dict:
    row = {
        "candidate_id": candidate["candidate_id"],
        "family": candidate["family"],
        "parameters_json": json.dumps(candidate, sort_keys=True),
        "feasible": metrics["feasible"],
        "failed_constraints_json": json.dumps(metrics["failed_constraints"]),
        "worst_subtype_review_or_higher_coverage": metrics[
            "worst_subtype_review_coverage"
        ],
        "macro_subtype_review_or_higher_coverage": metrics[
            "macro_subtype_review_coverage"
        ],
        "worst_subtype_block_coverage": metrics["worst_subtype_block_coverage"],
        "macro_subtype_block_coverage": metrics["macro_subtype_block_coverage"],
        "overall_attacker_review_or_higher_coverage": metrics[
            "attacker_review_or_higher"
        ]["rate"],
        "overall_attacker_block_coverage": metrics["attacker_block"]["rate"],
        "never_detected_attackers": metrics["never_detected_attackers"],
        "potentially_preventable_later_attempts_offline_upper_bound": metrics[
            "potentially_preventable_later_attempts_offline_upper_bound"
        ],
        "objective_tuple_json": json.dumps(comparison_tuple(metrics, candidate)),
        "metrics_json": json.dumps(metrics, sort_keys=True),
    }
    for name, budget in metrics["budget_results"].items():
        for field, value in budget.items():
            row[f"budget_{name}_{field}"] = value
    for name, subtype in metrics["subtype"].items():
        row[f"subtype_{name}_review_or_higher_coverage"] = subtype["review_or_higher"][
            "rate"
        ]
        row[f"subtype_{name}_block_coverage"] = subtype["block"]["rate"]
        row[f"subtype_{name}_never_detected"] = subtype["never_reviewed"]
    for limit, result in metrics["within_attempt"].items():
        row[f"detected_within_{limit}_attempts"] = result["review_or_higher"]
        row[f"blocked_within_{limit}_attempts"] = result["block"]
        row[f"attacker_denominator_within_{limit}_attempts"] = result["denominator"]
    for name, result in metrics["intervention_distributions"].items():
        for statistic, value in result.items():
            row[f"{name}_{statistic}"] = value
    return row


def static_model_diagnostics(
    features: pd.DataFrame, scorer: OptimizedFrozenScorer, candidates: list[dict]
):
    raw = scorer.artifact.predict_raw_proba(features)
    calibrated = scorer.artifact.predict_proba(features)
    weights = device_evaluation_weights(features)
    thresholds = sorted(
        {
            float(value)
            for candidate in candidates
            for key, value in candidate.items()
            if "threshold" in key
        }
    )
    threshold_rows = []
    labels = features.label.to_numpy(dtype=int)
    for threshold in thresholds:
        predicted = calibrated >= threshold
        tp = float(weights[(predicted) & (labels == 1)].sum())
        fp = float(weights[(predicted) & (labels == 0)].sum())
        fn = float(weights[(~predicted) & (labels == 1)].sum())
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        threshold_rows.append(
            {
                "threshold": threshold,
                "precision": precision,
                "recall": recall,
                "f1": 2 * precision * recall / (precision + recall)
                if precision + recall
                else 0.0,
                "weighted_true_positive": tp,
                "weighted_false_positive": fp,
                "weighted_false_negative": fn,
                "true_positive_rows": int(((predicted) & (labels == 1)).sum()),
                "false_positive_rows": int(((predicted) & (labels == 0)).sum()),
                "false_negative_rows": int(((~predicted) & (labels == 1)).sum()),
            }
        )
    diagnostic_rows = []
    scored = features[["scenario_tag", "attack_subtype", "label"]].copy()
    scored["probability"] = calibrated
    for dimension in ("scenario_tag", "attack_subtype"):
        for name, group in scored.groupby(dimension, dropna=False, sort=True):
            diagnostic_rows.append(
                {
                    "dimension": dimension,
                    "group": str(name),
                    "rows": len(group),
                    "positive_rows": int(group.label.sum()),
                    "mean_score": float(group.probability.mean()),
                    "p50_score": float(group.probability.median()),
                    "p90_score": float(group.probability.quantile(0.9)),
                }
            )
    metrics = {
        "scope": "one-time fresh validation diagnostics; not blind-test results",
        "raw": probability_metrics(features.label, raw, weights),
        "calibrated": probability_metrics(features.label, calibrated, weights),
        "rows": len(features),
        "devices": int(features.device_id.nunique()),
    }
    return (
        metrics,
        reliability_table(labels, calibrated, weights),
        pd.DataFrame(threshold_rows),
        pd.DataFrame(diagnostic_rows),
    )


def benchmark_candidates(
    raw: pd.DataFrame,
    contract: pd.DataFrame,
    scorer: OptimizedFrozenScorer,
    candidates: list[dict],
) -> dict:
    started = time.perf_counter()
    requests = int(raw.event_type.eq("authorization_request").sum())
    for candidate in candidates:
        replay_candidate(raw, contract, scorer, candidate)
    elapsed = time.perf_counter() - started
    candidate_requests = requests * len(candidates)
    return {
        "fixture_requests": requests,
        "candidate_count": len(candidates),
        "candidate_requests": candidate_requests,
        "runtime_seconds": elapsed,
        "effective_candidate_requests_per_second": candidate_requests / elapsed,
        "one_row_dataframe_per_request": False,
        "artifact_loads_per_process": 1,
        "model_calls_per_request": 1,
    }


def _final_hash_manifest(root: Path, relative_paths: list[str], output_path: Path):
    payload = {
        "version": "v2-phase2b-validation-final-hashes-1",
        "files": {name: sha256_file(root / name) for name in sorted(relative_paths)},
    }
    atomic_write_json(output_path, payload)
    atomic_write_text(
        output_path.with_suffix(".sha256"), sha256_file(output_path) + "\n"
    )
    return payload


def run_fresh_validation(root: Path) -> dict:
    """Perform the single authorized access and exactly 78 frozen replays."""
    output = root / "artifacts/v2/phase2b/validation"
    reports = root / "reports/v2/phase2b/validation"
    raw, contract, access = open_fresh_validation_once(
        root=root,
        output_dir=root / FRESH_RELATIVE_PATH,
        ledger_path=output / "access_ledger.json",
    )
    started = time.perf_counter()
    features, parity = verify_allow_all_parity(raw)
    artifact = joblib.load(
        root / "artifacts/v2/phase2b/training/models/selected_model.joblib"
    )
    scorer = OptimizedFrozenScorer(artifact)
    score_parity = scorer.verify_parity(features)
    parity["probability_parity"] = score_parity
    _write_csv(features, output / "allow_all_features.csv")
    atomic_write_json(output / "allow_all_parity.json", parity)

    policy = json.loads(
        (
            root / "artifacts/v2/phase2b/training/policy/policy_search_space.json"
        ).read_text()
    )
    candidates = policy["candidates"]
    if len(candidates) != 78 or len({row["candidate_id"] for row in candidates}) != 78:
        raise RuntimeError(
            "frozen policy space no longer contains exactly 78 candidates"
        )
    static, reliability, thresholds, groups = static_model_diagnostics(
        features, scorer, candidates
    )
    atomic_write_json(output / "static_model_metrics.json", static)
    _write_csv(reliability, output / "calibration_reliability.csv")
    _write_csv(thresholds, output / "static_threshold_metrics.csv")
    _write_csv(groups, output / "static_scenario_subtype_metrics.csv")

    budgets = policy["budgets"]
    expected_denominators = {
        "overall_legitimate": int(contract.label.eq(0).sum()),
        **{
            str(name): int(len(group))
            for name, group in contract.loc[contract.label.eq(0)].groupby(
                "scenario_tag", sort=True
            )
        },
    }
    for name, budget in budgets.items():
        if expected_denominators[name] != int(budget["denominator"]):
            raise RuntimeError(f"fresh-validation denominator mismatch: {name}")

    rows = []
    cached = {}
    replay_started = time.perf_counter()
    for candidate in candidates:
        _, devices = replay_candidate(raw, contract, scorer, candidate)
        metrics = detailed_candidate_metrics(devices, budgets)
        row = _candidate_row(candidate, metrics)
        rows.append(row)
        cached[candidate["candidate_id"]] = (candidate, devices, metrics)
    replay_seconds = time.perf_counter() - replay_started
    table = pd.DataFrame(rows)
    if len(table) != 78 or list(table.candidate_id) != [
        item["candidate_id"] for item in candidates
    ]:
        raise RuntimeError("candidate evaluation count or order changed")
    _write_csv(table, output / "policy_candidates.csv")
    feasible = [value for value in cached.values() if value[2]["feasible"]]
    status = "completed_blocked"
    champion = None
    champion_metrics = None
    champion_devices = None
    if feasible:
        selected = max(feasible, key=lambda value: comparison_tuple(value[2], value[0]))
        champion, first_devices, champion_metrics = selected
        decisions, repeat_devices = replay_candidate(
            raw, contract, scorer, champion, capture_decisions=True
        )
        repeat_metrics = detailed_candidate_metrics(repeat_devices, budgets)
        if json.dumps(repeat_metrics, sort_keys=True) != json.dumps(
            champion_metrics, sort_keys=True
        ) or not first_devices.equals(repeat_devices):
            raise RuntimeError("champion independent replay did not reproduce")
        champion_devices = repeat_devices
        _write_csv(decisions, output / "champion_decisions.csv")
        _write_csv(champion_devices, output / "champion_device_summary.csv")
        operational = {
            "version": "v2-phase2b-operational-policy-1",
            "selected_utc": datetime.now(UTC).isoformat(),
            "policy": champion,
            "metrics": champion_metrics,
            "training_freeze_sha256": sha256_file(
                root / "artifacts/v2/phase2b/training/freeze/training_freeze.json"
            ),
            "execution_freeze_sha256": sha256_file(output / "execution_freeze.json"),
            "dataset_manifest_sha256": sha256_file(
                root / FRESH_RELATIVE_PATH / "manifest.json"
            ),
            "candidate_table_sha256": sha256_file(output / "policy_candidates.csv"),
            "blind_evaluated": False,
        }
        atomic_write_json(output / "frozen_operational_policy.json", operational)
        atomic_write_text(
            output / "frozen_operational_policy.sha256",
            sha256_file(output / "frozen_operational_policy.json") + "\n",
        )
        status = "completed_feasible"

    feasibility = {
        "status": status,
        "candidate_count": 78,
        "feasible_candidate_count": len(feasible),
        "family_feasible_counts": {
            family: int(table.loc[table.feasible & table.family.eq(family)].shape[0])
            for family in ("rules_only", "ml_only", "combined")
        },
        "champion": champion,
        "champion_metrics": champion_metrics,
    }
    if not feasible:
        ranked = sorted(
            cached.values(),
            key=lambda value: (
                sum(
                    row["review_excess_devices"] + row["block_excess_devices"]
                    for row in value[2]["budget_results"].values()
                ),
                tuple(
                    -number if isinstance(number, int | float) else number
                    for number in comparison_tuple(value[2], value[0])
                ),
            ),
        )
        feasibility["closest_infeasible"] = [
            {"candidate": item[0], "failed_constraints": item[2]["failed_constraints"]}
            for item in ranked[:3]
        ]
    atomic_write_json(output / "feasibility.json", feasibility)
    runtime_seconds = time.perf_counter() - started
    requests = int(raw.event_type.eq("authorization_request").sum())
    runtime = {
        "total_evaluation_runtime_seconds": runtime_seconds,
        "policy_replay_runtime_seconds": replay_seconds,
        "requests_processed_per_candidate": requests,
        "candidate_count": 78,
        "candidate_requests": requests * 78,
        "effective_candidate_requests_per_second": requests * 78 / replay_seconds,
        "artifact_loads": 1,
        "one_row_dataframes_per_request": 0,
    }
    atomic_write_json(output / "runtime.json", runtime)
    access["completed_utc"] = datetime.now(UTC).isoformat()
    access["status"] = status
    atomic_write_json(output / "access_ledger.json", access)
    reports.mkdir(parents=True, exist_ok=True)
    report_lines = [
        "# Phase 2B one-time fresh-validation closeout",
        "",
        f"- Status: `{status}`",
        "- Scope: one-time fresh validation; not blind-test performance",
        f"- Candidates evaluated: {len(table)}",
        f"- Feasible candidates: {len(feasible)}",
        f"- Champion: `{champion['candidate_id'] if champion else 'none'}`",
        f"- Evaluation runtime: {runtime_seconds:.6f} seconds",
        "- Blind, Phase 3, API, and dashboard work: not accessed or created",
        "- Preventable-later-attempt values are offline replay upper bounds only.",
    ]
    atomic_write_text(reports / "phase_closeout.md", "\n".join(report_lines) + "\n")
    protected = [
        str(path.relative_to(root))
        for base in (root / FRESH_RELATIVE_PATH, output, reports)
        for path in base.rglob("*")
        if path.is_file()
        and path.name not in {"final_hash_manifest.json", "final_hash_manifest.sha256"}
    ]
    final_hashes = _final_hash_manifest(
        root, protected, output / "final_hash_manifest.json"
    )
    return {
        "status": status,
        "access": access,
        "parity": parity,
        "static_metrics": static,
        "feasibility": feasibility,
        "runtime": runtime,
        "final_hashes": final_hashes,
    }
