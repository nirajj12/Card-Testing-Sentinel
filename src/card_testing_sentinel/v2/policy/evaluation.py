import json
import platform
import time
from datetime import UTC, datetime
from pathlib import Path

import joblib
import mlflow
import numpy as np
import pandas as pd
import yaml

from card_testing_sentinel.v2.evaluation.access import (
    ROOT,
    open_validation,
    sha256_file,
    verify_phase1_protected_inputs,
    verify_training_freeze,
    verify_v1_release,
)
from card_testing_sentinel.v2.evaluation.metrics import (
    probability_metrics,
    reliability_table,
)
from card_testing_sentinel.v2.evaluation.sequential import (
    candidate_metrics,
    proportion,
    replay_policy,
)
from card_testing_sentinel.v2.features.batch import replay_events
from card_testing_sentinel.v2.features.spec import MODEL_FEATURES
from card_testing_sentinel.v2.modeling.features import MODEL_FEATURE_COLUMNS
from card_testing_sentinel.v2.modeling.weights import device_evaluation_weights
from card_testing_sentinel.v2.policy.rules import evaluate_rules
from card_testing_sentinel.v2.policy.selection import (
    choose_action,
    comparison_tuple,
    enumerate_policy_grid,
)


class _DuplicatePredictionCache:
    """Avoid recomputing the same raw score immediately before calibration."""

    def __init__(self, artifact):
        self.artifact = artifact
        self._frame = None
        self._raw = None

    def predict_raw_proba(self, frame):
        raw = self.artifact.predict_raw_proba(frame)
        self._frame = frame
        self._raw = raw
        return raw

    def predict_proba(self, frame):
        if frame is not self._frame:
            return self.artifact.predict_proba(frame)
        raw = self._raw
        if self.artifact.calibration_method == "none":
            return raw
        if self.artifact.calibration_method == "sigmoid":
            return self.artifact.calibrator.predict_proba(raw.reshape(-1, 1))[:, 1]
        return np.asarray(self.artifact.calibrator.predict(raw), dtype=float)


def _allow_all_parity(raw: pd.DataFrame, frozen: pd.DataFrame) -> dict:
    replayed = replay_events(raw).sort_values("event_id").reset_index(drop=True)
    expected = frozen.sort_values("event_id").reset_index(drop=True)
    if list(replayed.event_id) != list(expected.event_id):
        raise RuntimeError("allow-all replay request identity mismatch")
    observed = replayed.loc[:, MODEL_FEATURES].to_numpy(dtype=float)
    reference = expected.loc[:, MODEL_FEATURES].to_numpy(dtype=float)
    maximum = float(np.max(np.abs(observed - reference)))
    # Phase 1 writes feature rows to six decimals and freezes 5e-7 as parity tolerance.
    if not np.allclose(observed, reference, rtol=0, atol=5e-7):
        raise RuntimeError(f"allow-all validation feature parity failed: {maximum}")
    return {
        "precheck_rows": len(expected),
        "features": len(MODEL_FEATURES),
        "maximum_absolute_difference": maximum,
        "passed": True,
    }


def _detailed_sequential_metrics(devices: pd.DataFrame) -> dict:
    result = {
        "all_devices": int(len(devices)),
        "all_attackers": int(devices.label.sum()),
    }
    attackers = devices.loc[devices.label.eq(1)]
    result["attacker_review_or_higher"] = proportion(attackers, "review_or_higher")
    result["attacker_block"] = proportion(attackers, "blocked")
    result["never_reviewed_attackers"] = int((~attackers.review_or_higher).sum())
    result["never_blocked_attackers"] = int((~attackers.blocked).sum())
    result["within_request"] = {}
    for limit in (1, 3, 5, 10):
        result["within_request"][str(limit)] = {
            "review_or_higher": {
                "numerator": int(
                    attackers.first_review_or_higher_request.le(limit).sum()
                ),
                "denominator": int(len(attackers)),
            },
            "block": {
                "numerator": int(attackers.first_block_request.le(limit).sum()),
                "denominator": int(len(attackers)),
            },
        }
    result["by_subtype"] = {}
    for subtype, group in attackers.groupby("attack_subtype"):
        result["by_subtype"][str(subtype)] = {
            "review_or_higher": proportion(group, "review_or_higher"),
            "block": proportion(group, "blocked"),
            "never_reviewed": int((~group.review_or_higher).sum()),
            "never_blocked": int((~group.blocked).sum()),
            "within_request": {
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
    legitimate = devices.loc[devices.label.eq(0)]
    result["legitimate"] = {
        "overall": {
            "review_or_higher": proportion(legitimate, "review_or_higher"),
            "block": proportion(legitimate, "blocked"),
        }
    }
    for scenario, group in legitimate.groupby("scenario_tag"):
        result["legitimate"][str(scenario)] = {
            "review_or_higher": proportion(group, "review_or_higher"),
            "block": proportion(group, "blocked"),
        }
    distribution_columns = [
        "requests_scored_through_first_action",
        "authorizations_processed_before_first_action",
        "distinct_cards_requested_through_first_action",
        "distinct_cards_processed_before_first_action",
        "seconds_to_first_review",
        "seconds_to_first_block",
    ]
    result["acted_on_attacker_distributions"] = {}
    for name in distribution_columns:
        values = attackers[name].dropna()
        result["acted_on_attacker_distributions"][name] = {
            "count": int(len(values)),
            "median": float(values.median()) if len(values) else None,
            "mean": float(values.mean()) if len(values) else None,
            "p90": float(values.quantile(0.90)) if len(values) else None,
            "maximum": float(values.max()) if len(values) else None,
        }
    result["potentially_preventable_later_requests_upper_bound"] = int(
        devices.potentially_preventable_later_requests_upper_bound.sum()
    )
    return result


def _benchmark(artifact, row: pd.DataFrame, candidate: dict, rule_score: int) -> dict:
    for _ in range(20):
        probability = float(artifact.predict_proba(row)[0])
        choose_action(candidate, probability, rule_score)
    model_times = []
    policy_times = []
    for _ in range(300):
        started = time.perf_counter_ns()
        probability = float(artifact.predict_proba(row)[0])
        model_times.append((time.perf_counter_ns() - started) / 1e6)
        started = time.perf_counter_ns()
        choose_action(candidate, probability, rule_score)
        policy_times.append((time.perf_counter_ns() - started) / 1e6)

    def values(samples):
        return {
            "p50_ms": float(np.percentile(samples, 50)),
            "p95_ms": float(np.percentile(samples, 95)),
            "p99_ms": float(np.percentile(samples, 99)),
            "sample_count": len(samples),
        }

    return {
        "model_precheck": values(model_times),
        "policy_decision": values(policy_times),
        "scope": (
            "warm local Python call; excludes future HTTP, network and durable state"
        ),
        "runtime": platform.platform(),
    }


def run_validation_policy_phase(root: Path = ROOT) -> dict:
    verify_training_freeze()
    features, raw, access = open_validation()
    parity = _allow_all_parity(raw, features)
    serialized_artifact = joblib.load(
        root / "artifacts/v2/models/calibrated_model.joblib"
    )
    artifact = _DuplicatePredictionCache(serialized_artifact)
    parity_sample = features.iloc[:100]
    expected_probability = serialized_artifact.predict_proba(parity_sample)
    artifact.predict_raw_proba(parity_sample)
    cached_probability = artifact.predict_proba(parity_sample)
    if not np.allclose(expected_probability, cached_probability, rtol=0, atol=1e-12):
        raise RuntimeError("duplicate-score cache changed calibrated probabilities")
    policy_config = yaml.safe_load((root / "configs/v2/policy.yaml").read_text())
    splits = pd.read_csv(root / "data/v2/development/device_splits.csv")
    contract = splits.loc[
        splits.split.eq("validation"),
        ["device_id", "population", "attack_subtype", "scenario_tag", "label"],
    ].copy()
    observed_denominators = {"overall_legitimate": int(contract.label.eq(0).sum())}
    observed_denominators.update(
        {
            str(key): int(value)
            for key, value in contract.loc[contract.label.eq(0)]
            .groupby("scenario_tag")
            .size()
            .items()
        }
    )
    for name, budget in policy_config["budgets"].items():
        if observed_denominators[name] != budget["denominator"]:
            raise RuntimeError(f"frozen validation denominator mismatch for {name}")
        if budget["review_or_higher_allowance"] != int(
            np.floor(budget["denominator"] * budget["review_or_higher_rate"])
        ):
            raise RuntimeError(f"review allowance rounding mismatch for {name}")
        if budget["block_allowance"] != int(
            np.floor(budget["denominator"] * budget["block_rate"])
        ):
            raise RuntimeError(f"block allowance rounding mismatch for {name}")

    candidate_rows = []
    cached = {}
    for candidate in enumerate_policy_grid(policy_config):
        decisions, devices = replay_policy(raw, artifact, candidate, contract)
        metrics = candidate_metrics(devices, policy_config["budgets"])
        objective = comparison_tuple(metrics, candidate)
        candidate_rows.append(
            {
                **candidate,
                "parameters_json": json.dumps(candidate, sort_keys=True),
                "feasible": metrics["feasible"],
                "worst_subtype_review_coverage": metrics[
                    "worst_subtype_review_coverage"
                ],
                "macro_subtype_review_coverage": metrics[
                    "macro_subtype_review_coverage"
                ],
                "worst_subtype_block_coverage": metrics["worst_subtype_block_coverage"],
                "macro_subtype_block_coverage": metrics["macro_subtype_block_coverage"],
                "median_processed_authorizations_before_first_action": metrics[
                    "median_processed_authorizations_before_first_action"
                ],
                "legitimate_review_or_higher": metrics["legitimate_review_or_higher"],
                "legitimate_blocks": metrics["legitimate_blocks"],
                "objective_tuple_json": json.dumps(objective),
                "budget_results_json": json.dumps(metrics["budgets"], sort_keys=True),
                "metrics_json": json.dumps(metrics, sort_keys=True),
            }
        )
        cached[candidate["candidate_id"]] = (
            candidate,
            decisions,
            devices,
            metrics,
            objective,
        )
    table = pd.DataFrame(candidate_rows)
    table_path = root / "artifacts/v2/metrics/validation_policy_candidates.csv"
    table.to_csv(table_path, index=False)
    feasible = [value for value in cached.values() if value[3]["feasible"]]
    if not feasible:
        raise RuntimeError(
            "no frozen validation policy candidate satisfies every budget"
        )
    winner = max(feasible, key=lambda value: value[4])
    selected, decisions, devices, selected_metrics, objective = winner
    repeat_decisions, repeat_devices = replay_policy(raw, artifact, selected, contract)
    if list(decisions.action) != list(repeat_decisions.action) or not np.allclose(
        decisions.calibrated_probability,
        repeat_decisions.calibrated_probability,
        equal_nan=True,
        rtol=0,
        atol=1e-12,
    ):
        raise RuntimeError("validation replay failed deterministic reproduction")
    decisions_path = root / "artifacts/v2/predictions/validation_decisions.csv"
    device_path = root / "artifacts/v2/predictions/validation_device_summary.csv"
    decisions.to_csv(decisions_path, index=False, float_format="%.15g")
    devices.to_csv(device_path, index=False, float_format="%.15g")

    weights = device_evaluation_weights(features)
    raw_probability = artifact.predict_raw_proba(features)
    calibrated_probability = artifact.predict_proba(features)
    static = {
        "uncalibrated": probability_metrics(features.label, raw_probability, weights),
        "calibrated": probability_metrics(
            features.label, calibrated_probability, weights
        ),
        "unit": "precheck rows with device evaluation weights",
    }
    reliability_table(features.label.to_numpy(), raw_probability, weights).to_csv(
        root / "artifacts/v2/metrics/validation_reliability_raw.csv", index=False
    )
    reliability_table(
        features.label.to_numpy(), calibrated_probability, weights
    ).to_csv(
        root / "artifacts/v2/metrics/validation_reliability_calibrated.csv", index=False
    )
    family_comparison = {}
    for family in ("rules_only", "ml_only", "combined"):
        available = [value for value in feasible if value[0]["family"] == family]
        if available:
            representative = max(available, key=lambda value: value[4])
            family_comparison[family] = {
                "candidate": representative[0],
                "metrics": representative[3],
                "objective_tuple": list(representative[4]),
            }
        else:
            family_comparison[family] = {"feasible_candidate": False}
    sequential = _detailed_sequential_metrics(devices)
    first_row = features.iloc[[0]].loc[:, MODEL_FEATURE_COLUMNS]
    first_rules, _ = evaluate_rules(features.iloc[0].to_dict())
    latency = _benchmark(artifact, first_row, selected, first_rules)
    metrics_payload = {
        "version": "v2-phase2-validation-1",
        "first_validation_access": access,
        "allow_all_parity": parity,
        "validation_denominators": observed_denominators,
        "frozen_budgets": policy_config["budgets"],
        "candidate_count": int(len(table)),
        "feasible_candidate_count": int(table.feasible.sum()),
        "family_feasible_counts": {
            str(key): int(value)
            for key, value in table.loc[table.feasible].groupby("family").size().items()
        },
        "selected_policy": selected,
        "selected_objective_tuple": list(objective),
        "selected_metrics": selected_metrics,
        "static_probability_metrics": static,
        "sequential_metrics": sequential,
        "matched_budget_family_comparison": family_comparison,
        "latency": latency,
        "intervention_semantics": (
            "block_current_attempt suppresses its outcome and all later device "
            "state; review processes the recorded outcome; later requests after "
            "block are counterfactual upper-bound evidence only"
        ),
    }
    metrics_path = root / "artifacts/v2/metrics/validation_metrics.json"
    metrics_path.write_text(
        json.dumps(metrics_payload, indent=2, sort_keys=True) + "\n"
    )
    policy_payload = {
        "version": "v2-phase2-policy-1",
        "frozen_utc": datetime.now(UTC).isoformat(),
        "training_freeze_sha256": sha256_file(
            root / "artifacts/v2/training/training_freeze.json"
        ),
        "policy": selected,
        "objective_tuple": list(objective),
        "budgets": policy_config["budgets"],
        "rule_definitions_sha256": sha256_file(root / "artifacts/v2/policy/rules.json"),
        "model_artifact_sha256": sha256_file(
            root / "artifacts/v2/models/calibrated_model.joblib"
        ),
    }
    policy_path = root / "artifacts/v2/policy/frozen_policy.json"
    policy_path.write_text(json.dumps(policy_payload, indent=2, sort_keys=True) + "\n")
    report = [
        "# V2 Phase 2 validation and policy report",
        "",
        (
            f"Training freeze was created at "
            f"`{access['training_freeze_created_utc']}`; first validation access "
            f"was `{access['first_validation_access_utc']}`."
        ),
        "",
        (
            f"Allow-all parity passed for {parity['precheck_rows']:,} precheck "
            f"rows and {parity['features']} causal features (maximum absolute "
            f"difference {parity['maximum_absolute_difference']:.3g})."
        ),
        "",
        (
            f"The complete frozen grid contained {len(table)} candidates; "
            f"{int(table.feasible.sum())} satisfied every overall and subgroup "
            "allowance."
        ),
        (
            f"Selected `{selected['candidate_id']}` (`{selected['family']}`) "
            f"with objective tuple `{list(objective)}`."
        ),
        "",
        (
            f"Attacker review-or-higher: "
            f"{sequential['attacker_review_or_higher']['numerator']}/"
            f"{sequential['attacker_review_or_higher']['denominator']}; blocked: "
            f"{sequential['attacker_block']['numerator']}/"
            f"{sequential['attacker_block']['denominator']}."
        ),
        (
            f"Legitimate review-or-higher: "
            f"{selected_metrics['legitimate_review_or_higher']}/1700; blocked: "
            f"{selected_metrics['legitimate_blocks']}/1700."
        ),
        (
            "Potentially preventable later requests (offline upper bound, not "
            "observed prevented fraud): "
            f"{sequential['potentially_preventable_later_requests_upper_bound']}."
        ),
    ]
    report_path = root / "reports/v2/modeling/validation_policy_report.md"
    report_path.write_text("\n".join(report) + "\n")

    frozen_outputs = [
        "artifacts/v2/policy/frozen_policy.json",
        "artifacts/v2/predictions/validation_decisions.csv",
        "artifacts/v2/predictions/validation_device_summary.csv",
        "artifacts/v2/metrics/validation_policy_candidates.csv",
        "artifacts/v2/metrics/validation_metrics.json",
        "artifacts/v2/metrics/validation_reliability_raw.csv",
        "artifacts/v2/metrics/validation_reliability_calibrated.csv",
        "reports/v2/modeling/validation_policy_report.md",
    ]
    output_manifest = {name: sha256_file(root / name) for name in frozen_outputs}
    manifest_path = root / "artifacts/v2/phase2_artifact_hashes.json"
    manifest_path.write_text(
        json.dumps(output_manifest, indent=2, sort_keys=True) + "\n"
    )
    verify_phase1_protected_inputs()
    verify_v1_release()
    mlflow.set_tracking_uri((root / "mlruns").as_uri())
    mlflow.set_experiment("card-testing-sentinel-v2-policy")
    with mlflow.start_run(run_name="validation-policy-freeze"):
        mlflow.log_params(
            {
                "candidate_id": selected["candidate_id"],
                "family": selected["family"],
                "training_freeze_sha256": policy_payload["training_freeze_sha256"],
            }
        )
        mlflow.log_metrics(
            {
                "feasible_candidates": int(table.feasible.sum()),
                "worst_subtype_review_coverage": selected_metrics[
                    "worst_subtype_review_coverage"
                ],
                "legitimate_blocks": selected_metrics["legitimate_blocks"],
            }
        )
        mlflow.log_artifact(str(policy_path), artifact_path="policy")
    return {
        "selected_policy": selected,
        "objective_tuple": list(objective),
        "candidate_count": int(len(table)),
        "feasible_candidate_count": int(table.feasible.sum()),
        "metrics_path": str(metrics_path),
        "policy_path": str(policy_path),
    }
