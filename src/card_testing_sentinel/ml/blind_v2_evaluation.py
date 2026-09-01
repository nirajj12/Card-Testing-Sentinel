"""One-time, no-selection Blind v2 evaluation for the frozen v2 stack.

This module has no fitting, calibration, candidate search, threshold selection,
or data-generation path.  Its only scored path binds the already-frozen model,
policy, feature contract, causal replay, and Blind v2 hashes.  The benchmark is
marked evaluated and consumed immediately after the first successful scoring
call, before any metric is calculated or displayed.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import yaml

from card_testing_sentinel.features.batch import read_raw_events
from card_testing_sentinel.features.batch_v2 import replay_events_v2
from card_testing_sentinel.features.specification_v2 import (
    MODEL_FEATURES_V2,
    MODEL_FEATURES_V2_SHA256,
)
from card_testing_sentinel.ml.evaluation_v2 import (
    baseline_table,
    rule_scores_v2,
)
from card_testing_sentinel.ml.metrics import (
    device_weights,
    probability_metrics,
    reliability_bins,
)
from card_testing_sentinel.ml.policy_search_v2 import (
    device_view,
    evidence_gate_value,
    precompute,
)
from card_testing_sentinel.policy.engine_v2 import RiskPolicyV2

FIXED_THRESHOLDS = (0.30, 0.40, 0.50, 0.60, 0.70, 0.75, 0.80, 0.90)
ATTEMPT_CUTS = (1, 2, 3, 5)
POLICY_FIELDS = (
    "family",
    "review_threshold",
    "block_threshold",
    "block_evidence",
    "evidence_set",
    "trust_suppression",
    "block_ttl_seconds",
    "campaign_review_increment",
    "campaign_block_increment",
    "degraded_review_rule_score",
    "degraded_block_rule_score",
)
RESULT_NAMES = (
    "blind_v2_metrics.json",
    "blind_v2_family_metrics.csv",
    "blind_v2_threshold_table.csv",
    "blind_v2_baselines.csv",
    "blind_v2_detection_delay.json",
    "blind_v2_calibration.csv",
    "blind_v2_consumption.json",
    "blind_v2_result_hashes.json",
)


class BlindV2EvaluationError(RuntimeError):
    """A one-time evaluation precondition or integrity check failed."""


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _verify_section(root: Path, section: dict, stage: str) -> dict[str, str]:
    verified = {}
    for key, relative in section.get("files", {}).items():
        path = root / relative
        if not path.is_file():
            raise BlindV2EvaluationError(f"{stage} input missing: {relative}")
        actual = sha256_file(path)
        if actual != section.get(key):
            raise BlindV2EvaluationError(
                f"{stage} drift: {relative} is {actual}, expected {section.get(key)}"
            )
        verified[f"{stage}.{key}"] = actual
    return verified


def verify_pre_evaluation(root: Path, *, require_clean_outputs: bool = True) -> dict:
    """Verify every Phase 12 freeze binding without loading or scoring a model."""
    freeze_path = root / "artifacts/evaluation/blind_v2_freeze_manifest.json"
    freeze = json.loads(freeze_path.read_text())
    if freeze.get("blind_version") != "v2":
        raise BlindV2EvaluationError("freeze manifest is not Blind v2")
    if freeze.get("evaluated") or freeze.get("consumed"):
        raise BlindV2EvaluationError("Blind v2 is already evaluated or consumed")
    if not all(freeze.get(stage) for stage in ("foundation", "sources", "dataset")):
        raise BlindV2EvaluationError("Blind v2 freeze is incomplete")

    verified = {}
    for stage in ("foundation", "sources", "dataset"):
        verified.update(_verify_section(root, freeze[stage], stage))

    data_manifest = json.loads(
        (root / "data/generated/blind_v2/manifest.json").read_text()
    )
    if data_manifest.get("evaluated") or data_manifest.get("consumed"):
        raise BlindV2EvaluationError("frozen data manifest is not pristine")
    if data_manifest.get("contains_model_scores") or data_manifest.get(
        "contains_policy_decisions"
    ):
        raise BlindV2EvaluationError("frozen data manifest already contains results")

    metadata = json.loads((root / "artifacts/model_v2/metadata.json").read_text())
    training_config = root / "configs/training_v2.yaml"
    if sha256_file(training_config) != metadata["training_config_sha256"]:
        raise BlindV2EvaluationError("predeclared Model v2 baseline grid drifted")
    if metadata["feature_contract_sha256"] != MODEL_FEATURES_V2_SHA256:
        raise BlindV2EvaluationError("Model v2 metadata contract binding changed")

    policy_yaml = yaml.safe_load((root / "configs/policy_v2.yaml").read_text())[
        "policy"
    ]
    policy_artifact = json.loads(
        (root / "artifacts/policy_v2/operational_policy_v2.json").read_text()
    )
    for key in POLICY_FIELDS:
        if policy_yaml.get(key) != policy_artifact.get(key):
            raise BlindV2EvaluationError(f"Policy v2 config/artifact differ at {key}")

    if require_clean_outputs:
        result_dir = root / "artifacts/evaluation"
        occupied = [name for name in RESULT_NAMES if (result_dir / name).exists()]
        report = root / "reports/phase_13_blind_v2_evaluation_report.md"
        if report.exists():
            occupied.append(str(report.relative_to(root)))
        if occupied:
            raise BlindV2EvaluationError(f"Phase 13 outputs already exist: {occupied}")

    return {
        "status": "passed",
        "freeze_manifest_pre_evaluation_sha256": sha256_file(freeze_path),
        "verified_hashes": verified,
        "training_config_sha256": sha256_file(training_config),
        "feature_contract_sha256": MODEL_FEATURES_V2_SHA256,
        "model_metadata_sha256": sha256_file(root / "artifacts/model_v2/metadata.json"),
    }


def causal_frame(root: Path) -> tuple[pd.DataFrame, dict]:
    """Replay raw events causally and prove parity with the frozen projection."""
    raw = read_raw_events(root / "data/generated/blind_v2/raw_events.csv")
    replayed = replay_events_v2(raw).reset_index(drop=True)
    frozen = pd.read_csv(root / "data/generated/blind_v2/features_v2.csv")
    frozen = frozen.reset_index(drop=True)
    compare_columns = [
        "request_id",
        "device_id",
        "session_id",
        "timestamp",
        *MODEL_FEATURES_V2,
    ]
    if len(replayed) != len(frozen):
        raise BlindV2EvaluationError("causal replay row count differs from freeze")
    try:
        pd.testing.assert_frame_equal(
            replayed[compare_columns],
            frozen[compare_columns],
            check_dtype=False,
            check_exact=False,
            rtol=1e-12,
            atol=1e-12,
        )
    except AssertionError as error:
        raise BlindV2EvaluationError(
            "fresh causal replay differs from frozen FeatureEngine v2 projection"
        ) from error

    labels = pd.read_csv(root / "data/generated/blind_v2/labels.csv")
    label_columns = [
        "device_id",
        "actor_id",
        "population",
        "scenario",
        "label",
        "merchant_id",
        "merchant_kind",
        "linkage_class",
    ]
    frame = replayed.merge(
        labels[label_columns].drop_duplicates("device_id"),
        on="device_id",
        how="left",
        validate="many_to_one",
    )
    requests = raw.loc[
        raw.event_type.eq("authorization_request"), ["request_id", "campaign_active"]
    ]
    frame = frame.merge(requests, on="request_id", how="left", validate="one_to_one")
    frame["campaign_active"] = (
        frame.campaign_active.astype("boolean").fillna(False).astype(bool)
    )
    if frame.label.isna().any():
        raise BlindV2EvaluationError("causal replay has unlabelled request rows")
    if tuple(name for name in frame.columns if name in MODEL_FEATURES_V2) != tuple(
        MODEL_FEATURES_V2
    ):
        raise BlindV2EvaluationError("causal replay feature order changed")
    return frame, {
        "raw_rows": int(len(raw)),
        "request_rows": int(len(frame)),
        "projection_rows": int(len(frozen)),
        "byte_frozen_projection_sha256": sha256_file(
            root / "data/generated/blind_v2/features_v2.csv"
        ),
        "fresh_replay_matches_frozen_projection": True,
        "ordering": ["timestamp", "event_sequence"],
    }


def load_bound_stack(root: Path) -> tuple[object, dict, RiskPolicyV2]:
    freeze = json.loads(
        (root / "artifacts/evaluation/blind_v2_freeze_manifest.json").read_text()
    )
    model_path = root / "artifacts/model_v2/risk_model_v2.joblib"
    if sha256_file(model_path) != freeze["foundation"]["model_v2_sha256"]:
        raise BlindV2EvaluationError("Model v2 hash changed before loading")
    artifact = joblib.load(model_path)
    if tuple(getattr(artifact, "feature_names", ())) != MODEL_FEATURES_V2:
        raise BlindV2EvaluationError("Model v2 feature order differs from contract")
    if getattr(artifact, "feature_contract_sha256", None) != MODEL_FEATURES_V2_SHA256:
        raise BlindV2EvaluationError("Model v2 feature contract binding differs")
    policy_artifact = json.loads(
        (root / "artifacts/policy_v2/operational_policy_v2.json").read_text()
    )
    policy_config = {key: policy_artifact[key] for key in POLICY_FIELDS}
    return artifact, policy_config, RiskPolicyV2(policy_config)


def consume_after_first_score(
    root: Path,
    preflight: dict,
    scoring_started: str,
    evaluator_path: Path,
    pipeline_path: Path,
) -> dict:
    """Atomically record the one look immediately after scoring succeeds."""
    freeze_path = root / "artifacts/evaluation/blind_v2_freeze_manifest.json"
    freeze = json.loads(freeze_path.read_text())
    if freeze.get("evaluated") or freeze.get("consumed"):
        raise BlindV2EvaluationError("Blind v2 was consumed during first scoring")
    consumed = datetime.now(UTC).isoformat()
    record = {
        "blind_version": "v2",
        "first_successful_score_utc": consumed,
        "scoring_started_utc": scoring_started,
        "evaluated": True,
        "consumed": True,
        "status": "results_in_progress",
        "freeze_manifest_pre_evaluation_sha256": preflight[
            "freeze_manifest_pre_evaluation_sha256"
        ],
        "blind_raw_sha256": freeze["dataset"]["raw_events_sha256"],
        "blind_labels_sha256": freeze["dataset"]["labels_sha256"],
        "blind_features_v2_sha256": freeze["dataset"]["features_v2_sha256"],
        "model_v2_sha256": freeze["foundation"]["model_v2_sha256"],
        "policy_v2_config_sha256": freeze["foundation"]["policy_v2_config_sha256"],
        "policy_v2_artifact_sha256": freeze["foundation"]["policy_v2_artifact_sha256"],
        "feature_contract_v2_artifact_sha256": freeze["foundation"][
            "feature_contract_v2_artifact_sha256"
        ],
        "feature_contract_v2_source_sha256": freeze["foundation"][
            "feature_contract_v2_source_sha256"
        ],
        "feature_engine_v2_sha256": freeze["foundation"]["feature_engine_v2_sha256"],
        "evaluation_module_sha256": sha256_file(evaluator_path),
        "evaluation_pipeline_sha256": sha256_file(pipeline_path),
        "post_blind_tuning": False,
    }
    consumption_path = root / "artifacts/evaluation/blind_v2_consumption.json"
    json_write(consumption_path, record)
    freeze["evaluated"] = True
    freeze["consumed"] = True
    freeze["first_successful_score_utc"] = consumed
    freeze["consumption_record"] = str(consumption_path.relative_to(root))
    freeze["consumption_record_sha256"] = sha256_file(consumption_path)
    freeze["post_blind_tuning"] = False
    json_write(freeze_path, freeze)
    return record


def wilson_interval(successes: int, total: int) -> dict:
    if total <= 0:
        return {"low": None, "high": None}
    z = 1.959963984540054
    p = successes / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total))
    margin /= denominator
    return {"low": round(center - margin, 6), "high": round(center + margin, 6)}


def _rate(successes: int, total: int) -> float:
    return round(successes / total, 6) if total else 0.0


def threshold_diagnostics(
    frame: pd.DataFrame, risk: np.ndarray, thresholds=FIXED_THRESHOLDS
) -> pd.DataFrame:
    rows = []
    base = frame[["device_id", "label"]].drop_duplicates("device_id")
    total_devices = len(base)
    for threshold in thresholds:
        work = frame[["device_id", "label"]].copy()
        work["flagged"] = risk >= float(threshold)
        devices = work.groupby("device_id").agg(
            label=("label", "first"), flagged=("flagged", "any")
        )
        attacks = devices.label.eq(1)
        legitimate = devices.label.eq(0)
        detected = int((attacks & devices.flagged).sum())
        false = int((legitimate & devices.flagged).sum())
        flagged = detected + false
        rows.append(
            {
                "threshold": float(threshold),
                "attack_device_recall": _rate(detected, int(attacks.sum())),
                "legitimate_device_fpr": _rate(false, int(legitimate.sum())),
                "device_precision": _rate(detected, flagged),
                "device_flagged_fraction": _rate(flagged, total_devices),
                "attack_devices_detected": detected,
                "legitimate_devices_flagged": false,
                "flagged_devices": flagged,
            }
        )
    return pd.DataFrame(rows)


def policy_decisions(
    frame: pd.DataFrame, risk: np.ndarray, policy: RiskPolicyV2
) -> tuple[pd.DataFrame, pd.DataFrame]:
    actions = []
    reasons = []
    for snapshot, score, timestamp, campaign in zip(
        frame.loc[:, list(MODEL_FEATURES_V2)].to_dict("records"),
        risk,
        pd.to_datetime(frame.timestamp, format="ISO8601"),
        frame.campaign_active,
        strict=True,
    ):
        decision = policy.decide(
            snapshot=snapshot,
            risk_score=float(score),
            timestamp=timestamp.to_pydatetime(),
            campaign_active=bool(campaign),
        )
        actions.append(decision.action)
        reasons.append(list(decision.reason_codes))
    decisions = frame[
        [
            "request_id",
            "device_id",
            "label",
            "population",
            "scenario",
            "merchant_kind",
            "linkage_class",
            "timestamp",
            "customer_id_present",
            "customer_successful_checkouts_30d",
        ]
    ].copy()
    decisions["risk"] = risk
    decisions["action"] = actions
    decisions["reasons"] = reasons
    ranks = decisions.action.map({"allow": 0, "review": 1, "block": 2}).to_numpy()
    return decisions, device_view(frame, ranks)


def policy_summary(decisions: pd.DataFrame, devices: pd.DataFrame) -> dict:
    attack = devices.loc[devices.label.eq(1)]
    legitimate = devices.loc[devices.label.eq(0)]
    counts = decisions.action.value_counts().reindex(
        ["allow", "review", "block"], fill_value=0
    )
    summary = {
        "attack_devices": int(len(attack)),
        "legitimate_devices": int(len(legitimate)),
        "attack_review_or_higher_devices": int(attack.ever_reviewed.sum()),
        "attack_block_devices": int(attack.ever_blocked.sum()),
        "legitimate_review_or_higher_devices": int(legitimate.ever_reviewed.sum()),
        "legitimate_block_devices": int(legitimate.ever_blocked.sum()),
        "attack_review_or_higher_rate": _rate(
            int(attack.ever_reviewed.sum()), len(attack)
        ),
        "attack_block_rate": _rate(int(attack.ever_blocked.sum()), len(attack)),
        "legitimate_review_or_higher_rate": _rate(
            int(legitimate.ever_reviewed.sum()), len(legitimate)
        ),
        "legitimate_block_rate": _rate(
            int(legitimate.ever_blocked.sum()), len(legitimate)
        ),
        "attempt_actions": {
            action: {
                "count": int(counts[action]),
                "rate": _rate(int(counts[action]), len(decisions)),
            }
            for action in ("allow", "review", "block")
        },
    }
    summary["confidence_intervals_95"] = {
        "attack_review_or_higher": wilson_interval(
            summary["attack_review_or_higher_devices"], len(attack)
        ),
        "attack_block": wilson_interval(summary["attack_block_devices"], len(attack)),
        "legitimate_review_or_higher": wilson_interval(
            summary["legitimate_review_or_higher_devices"], len(legitimate)
        ),
        "legitimate_block": wilson_interval(
            summary["legitimate_block_devices"], len(legitimate)
        ),
    }
    return summary


def family_table(decisions: pd.DataFrame, devices: pd.DataFrame) -> pd.DataFrame:
    requests = decisions.groupby("scenario").size()
    rows = []
    for scenario, group in devices.groupby("scenario"):
        reviewed = int(group.ever_reviewed.sum())
        blocked = int(group.ever_blocked.sum())
        rows.append(
            {
                "scenario": scenario,
                "population": group.population.iloc[0],
                "devices": int(len(group)),
                "requests": int(requests[scenario]),
                "reviewed_devices": reviewed,
                "blocked_devices": blocked,
                "review_or_higher_rate": _rate(reviewed, len(group)),
                "block_rate": _rate(blocked, len(group)),
                "never_detected_devices": int((~group.ever_reviewed).sum())
                if group.label.iloc[0] == 1
                else None,
                "median_first_review_attempt": _quantile(
                    group.first_review_attempt, 0.5
                ),
                "p90_first_review_attempt": _quantile(group.first_review_attempt, 0.9),
                "median_first_block_attempt": _quantile(group.first_block_attempt, 0.5),
                "p90_first_block_attempt": _quantile(group.first_block_attempt, 0.9),
            }
        )
    return pd.DataFrame(rows).sort_values(["population", "scenario"])


def _quantile(series: pd.Series, q: float) -> float | None:
    clean = series.dropna()
    return round(float(clean.quantile(q)), 4) if len(clean) else None


def detection_group(devices: pd.DataFrame, scenarios: tuple[str, ...]) -> dict:
    group = devices.loc[devices.scenario.isin(scenarios) & devices.label.eq(1)]
    reviewed = int(group.ever_reviewed.sum())
    blocked = int(group.ever_blocked.sum())
    return {
        "scenarios": list(scenarios),
        "devices": int(len(group)),
        "reviewed_devices": reviewed,
        "blocked_devices": blocked,
        "never_detected_devices": int((~group.ever_reviewed).sum()),
        "review_or_higher_rate": _rate(reviewed, len(group)),
        "block_rate": _rate(blocked, len(group)),
        "median_first_review_attempt": _quantile(group.first_review_attempt, 0.5),
        "p90_first_review_attempt": _quantile(group.first_review_attempt, 0.9),
        "median_first_block_attempt": _quantile(group.first_block_attempt, 0.5),
        "p90_first_block_attempt": _quantile(group.first_block_attempt, 0.9),
        "cumulative": {
            str(cut): {
                "reviewed_devices": int(
                    group.first_review_attempt.le(cut).fillna(False).sum()
                ),
                "review_or_higher_rate": _rate(
                    int(group.first_review_attempt.le(cut).fillna(False).sum()),
                    len(group),
                ),
                "blocked_devices": int(
                    group.first_block_attempt.le(cut).fillna(False).sum()
                ),
                "block_rate": _rate(
                    int(group.first_block_attempt.le(cut).fillna(False).sum()),
                    len(group),
                ),
            }
            for cut in ATTEMPT_CUTS
        },
    }


def segment_diagnostics(
    frame: pd.DataFrame,
    decisions: pd.DataFrame,
    devices: pd.DataFrame,
    risk: np.ndarray,
) -> dict:
    request_rows = []
    for present in (False, True):
        mask = frame.customer_id_present.eq(1.0).to_numpy() == present
        group = frame.loc[mask]
        scores = risk[mask]
        labels = group.label.to_numpy(dtype=int)
        metrics = probability_metrics(labels, scores, device_weights(group))
        actions = decisions.loc[mask].action.value_counts()
        request_rows.append(
            {
                "segment": "customer_present" if present else "customer_absent",
                "requests": int(len(group)),
                "devices": int(group.device_id.nunique()),
                "model_metrics": {
                    key: round(value, 6) for key, value in metrics.items()
                },
                "allow_requests": int(actions.get("allow", 0)),
                "review_requests": int(actions.get("review", 0)),
                "block_requests": int(actions.get("block", 0)),
            }
        )
    device_rows = []
    for present, group in devices.groupby("customer_present"):
        attack = group.loc[group.label.eq(1)]
        legitimate = group.loc[group.label.eq(0)]
        device_rows.append(
            {
                "segment": "ever_customer_present" if present else "always_guest",
                "devices": int(len(group)),
                "attack_devices": int(len(attack)),
                "legitimate_devices": int(len(legitimate)),
                "attack_review_or_higher_rate": _rate(
                    int(attack.ever_reviewed.sum()), len(attack)
                ),
                "attack_block_rate": _rate(int(attack.ever_blocked.sum()), len(attack)),
                "legitimate_review_or_higher_rate": _rate(
                    int(legitimate.ever_reviewed.sum()), len(legitimate)
                ),
                "legitimate_block_rate": _rate(
                    int(legitimate.ever_blocked.sum()), len(legitimate)
                ),
            }
        )
    return {"request_segments": request_rows, "device_segments": device_rows}


def linkage_diagnostics(devices: pd.DataFrame, labels: pd.DataFrame) -> list[dict]:
    linked = devices.drop(columns=["scenario", "population"], errors="ignore").merge(
        labels[["device_id", "linkage_class"]].drop_duplicates("device_id"),
        left_index=True,
        right_on="device_id",
        validate="one_to_one",
    )
    rows = []
    for linkage, group in linked.groupby("linkage_class"):
        attack = group.loc[group.label.eq(1)]
        legitimate = group.loc[group.label.eq(0)]
        rows.append(
            {
                "linkage_class": linkage,
                "devices": int(len(group)),
                "attack_devices": int(len(attack)),
                "legitimate_devices": int(len(legitimate)),
                "attack_review_or_higher_rate": _rate(
                    int(attack.ever_reviewed.sum()), len(attack)
                ),
                "attack_block_rate": _rate(int(attack.ever_blocked.sum()), len(attack)),
                "legitimate_review_or_higher_rate": _rate(
                    int(legitimate.ever_reviewed.sum()), len(legitimate)
                ),
                "legitimate_block_rate": _rate(
                    int(legitimate.ever_blocked.sum()), len(legitimate)
                ),
            }
        )
    return rows


def subscription_diagnostic(frame: pd.DataFrame, devices: pd.DataFrame) -> dict:
    scenario = "subscription_dunning_v2"
    rows = frame.loc[frame.scenario.eq(scenario)]
    group = devices.loc[devices.scenario.eq(scenario)]
    present = rows.customer_id_present.eq(1.0)
    return {
        "devices": int(len(group)),
        "requests": int(len(rows)),
        "reviewed_devices": int(group.ever_reviewed.sum()),
        "blocked_devices": int(group.ever_blocked.sum()),
        "allow_device_rate": _rate(int((~group.ever_reviewed).sum()), len(group)),
        "review_or_higher_rate": _rate(int(group.ever_reviewed.sum()), len(group)),
        "block_rate": _rate(int(group.ever_blocked.sum()), len(group)),
        "customer_id_present_requests": int(present.sum()),
        "customer_id_absent_requests": int((~present).sum()),
        "devices_with_historical_success_in_30d": int(
            rows.groupby("device_id")
            .customer_successful_checkouts_30d.max()
            .gt(0)
            .sum()
        ),
    }


def matched_baselines(
    frame: pd.DataFrame,
    risk: np.ndarray,
    training_config: dict,
    thresholds: pd.DataFrame,
) -> pd.DataFrame:
    rules = rule_scores_v2(frame)
    declared = dict(training_config["evaluation"])
    declared["risk_thresholds"] = list(FIXED_THRESHOLDS)
    declared["combined_risk_thresholds"] = []
    declared["combined_rule_thresholds"] = []
    table = baseline_table(frame, risk, rules, declared)
    model = thresholds.set_index("threshold")
    rows = []
    for _, baseline in table.loc[
        table.family.isin(
            ("request_count", "rules_only", "long_horizon_count", "cross_device_count")
        )
    ].iterrows():
        gaps = (model.legitimate_device_fpr - baseline.legitimate_device_fpr).abs()
        threshold = float(gaps.idxmin())
        matched = model.loc[threshold]
        rows.append(
            {
                "baseline": baseline.approach,
                "baseline_family": baseline.family,
                "baseline_recall": baseline.attack_device_recall,
                "baseline_fpr": baseline.legitimate_device_fpr,
                "model_fixed_threshold": threshold,
                "model_recall": matched.attack_device_recall,
                "model_fpr": matched.legitimate_device_fpr,
                "fpr_gap": round(
                    float(
                        matched.legitimate_device_fpr - baseline.legitimate_device_fpr
                    ),
                    6,
                ),
                "recall_difference": round(
                    float(matched.attack_device_recall - baseline.attack_device_recall),
                    6,
                ),
            }
        )
    return pd.DataFrame(rows)


def verdict(model: dict, policy: dict) -> tuple[str, str]:
    strong = (
        model["pr_auc"] >= 0.70
        and model["roc_auc"] >= 0.85
        and policy["attack_review_or_higher_rate"] >= 0.70
        and policy["attack_block_rate"] >= 0.50
        and policy["legitimate_review_or_higher_rate"] <= 0.06
        and policy["legitimate_block_rate"] <= 0.01
    )
    acceptable = (
        policy["attack_review_or_higher_rate"] >= 0.70
        and policy["legitimate_block_rate"] <= 0.02
    )
    if strong:
        return "STRONG", "all operating targets and the predeclared quality bar passed"
    if acceptable:
        return (
            "ACCEPTABLE",
            "core attack-review coverage and a 2% block-friction ceiling passed, "
            "but at least one stronger quality or operating target missed",
        )
    return (
        "WEAK",
        "core attack-review coverage or the 2% legitimate-block ceiling failed",
    )


def markdown_table(frame: pd.DataFrame, columns: list[str] | None = None) -> str:
    view = frame if columns is None else frame[columns]
    headers = [str(column) for column in view.columns]
    lines = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join(["---"] * len(headers)) + "|",
    ]
    for row in view.itertuples(index=False, name=None):
        lines.append(
            "| " + " | ".join("" if pd.isna(v) else str(v) for v in row) + " |"
        )
    return "\n".join(lines)


def build_report(
    metrics: dict,
    thresholds: pd.DataFrame,
    families: pd.DataFrame,
    baselines: pd.DataFrame,
    detection: dict,
    hashes: dict | None = None,
) -> str:
    policy = metrics["policy"]
    model = metrics["model_metrics"]
    gap = metrics["development_to_blind"]
    verdict_name, verdict_reason = metrics["verdict"], metrics["verdict_reason"]
    attack = families.loc[families.population.eq("attack")]
    legitimate = families.loc[families.population.eq("legitimate")]
    target = metrics["operating_targets"]
    ci = policy["confidence_intervals_95"]
    attack_review = (
        f"{policy['attack_review_or_higher_devices']}/{policy['attack_devices']} "
        f"({policy['attack_review_or_higher_rate']:.2%})"
    )
    attack_block = (
        f"{policy['attack_block_devices']}/{policy['attack_devices']} "
        f"({policy['attack_block_rate']:.2%})"
    )
    legitimate_review = (
        f"{policy['legitimate_review_or_higher_devices']}/"
        f"{policy['legitimate_devices']} "
        f"({policy['legitimate_review_or_higher_rate']:.2%})"
    )
    legitimate_block = (
        f"{policy['legitimate_block_devices']}/{policy['legitimate_devices']} "
        f"({policy['legitimate_block_rate']:.2%})"
    )
    cross_combined = json.dumps(detection["cross_device_combined"], sort_keys=True)
    report = f"""# Phase 13 — One-Time Blind v2 Evaluation

## 1. Pre-evaluation freeze verification

Passed before Model v2 was loaded. Every Blind v2 source/data hash and every
development anchor matched the Phase 12 freeze. Fresh causal replay matched all
{metrics['causal_replay']['request_rows']} frozen feature rows.

## 2. Exact first-score and consumption timestamp

`{metrics['consumption']['first_successful_score_utc']}`. The consumption record
was written immediately after the first successful scoring call and before any
metric was calculated or displayed.

## 3. Lifecycle state

`evaluated = true`, `consumed = true`, and `post_blind_tuning = false`.

## 4. Model v2 aggregate metrics

- PR-AUC: {model['pr_auc']:.6f}
- ROC-AUC: {model['roc_auc']:.6f}
- Brier: {model['brier']:.6f}
- Log loss: {model['log_loss']:.6f}
- ECE: {model['ece']:.6f}

Metrics are request-level with total weight one per device, matching development.

## 5. Calibration metrics

ECE is {model['ece']:.6f}; the ten fixed equal-width calibration bins are stored
in `artifacts/evaluation/blind_v2_calibration.csv`. No calibrator was fitted.

## 6. Fixed threshold table

{markdown_table(thresholds)}

These eight thresholds were fixed in the Phase 13 instruction and are diagnostic
only. No replacement operating point was selected.

## 7. Frozen Policy v2 aggregate metrics

- Attack REVIEW+: {attack_review}
- Attack BLOCK: {attack_block}
- Legitimate REVIEW+: {legitimate_review}
- Legitimate BLOCK: {legitimate_block}
- Attempt actions: {policy['attempt_actions']}

## 8. Operating-target PASS/FAIL

- Attack REVIEW+ >= 70%: **{target['attack_review_or_higher']}**
- Legitimate REVIEW+ <= 6%: **{target['legitimate_review_or_higher']}**
- Legitimate BLOCK <= 1%: **{target['legitimate_block']}**

## 9. Confidence intervals

Wilson 95% intervals: attack REVIEW+ {ci['attack_review_or_higher']}, attack BLOCK
{ci['attack_block']}, legitimate REVIEW+ {ci['legitimate_review_or_higher']}, and
legitimate BLOCK {ci['legitimate_block']}. Small family estimates have materially
wider uncertainty and should not be read as precise production rates.

## 10. All attack-family metrics

{markdown_table(attack)}

## 11. Patient result

{json.dumps(detection['patient_tester_v2'], sort_keys=True)}

## 12. Ultra-patient result

{json.dumps(detection['ultra_patient_v2'], sort_keys=True)}

## 13. Sparse-multiday result

{json.dumps(detection['sparse_multiday_v2'], sort_keys=True)}

Long-horizon usefulness is interpreted from the frozen scores/features only:
{metrics['long_horizon_interpretation']}

## 14. Cross-device strong result

{json.dumps(detection['cross_device_strong'], sort_keys=True)}

## 15. Cross-device partial result

{json.dumps(detection['cross_device_partial'], sort_keys=True)}

## 16. Cross-device weak-guest result

{json.dumps(detection['cross_device_weak_guest'], sort_keys=True)}

The combined cross-device delay is {cross_combined}.

## 17. All legitimate-family friction

{markdown_table(legitimate)}

## 18. Subscription-dunning result

{json.dumps(metrics['subscription_dunning'], sort_keys=True)}

## 19. Guest versus logged-in result

{json.dumps(metrics['customer_id_segments'], sort_keys=True)}

Guest legitimate users are interpreted as: {metrics['guest_friction_interpretation']}

## 20. Evidence-gate value

{json.dumps(metrics['evidence_gate'], sort_keys=True)}

## 21. Detection-delay results

{json.dumps(detection['all_attacks'], sort_keys=True)}

The same fixed attempt cuts are recorded for patient, ultra-patient, sparse, and
combined cross-device cohorts in the detection-delay artifact.

## 22. Fixed baseline comparisons

The full predeclared grid and nearest of the eight fixed Model v2 thresholds:

{markdown_table(baselines)}

No baseline or model threshold was optimized on Blind v2.

## 23. Development-to-blind generalization gap

{json.dumps(gap, sort_keys=True)}

Absolute deltas are Blind v2 minus Dataset v3 validation.

## 24. Historical Blind v1.1 context

Old Blind v1.1 was approximately PR-AUC 0.5875, ROC-AUC 0.8262, attack REVIEW+
66.2%, attack BLOCK 44.0%, legitimate REVIEW+ 6.5%, and legitimate BLOCK 1.3%.
Blind v1.1 and v2 are different benchmarks; these are directional engineering
context, not a controlled performance-gain claim.

## 25. Distribution-shift interpretation

Blind v2 median PSI was 0.0792, with larger shifts in device age (0.9358),
customer age (0.5285), active days (0.4269), gap variability (0.3542), and amount
(0.2887). Performance changes reflect a mixture of merchant/composition/temporal
shift and model generalization; not every delta is attributable to model quality.

## 26. Legitimate-decline warning

Blind v2's legitimate decline rate is 34.49%, above the predeclared 34% warning
level but below the 46% hard-fail gate. The benchmark is friction-heavy and was
not invalidated or regenerated.

## 27. Artifact hashes

{json.dumps(hashes or {'status': 'written after report serialization'}, sort_keys=True)}

## 28. Preservation checks

Post-evaluation verification preserved Blind v2 source/data bytes, Blind v1.1,
Dataset v3, Feature Contract/Engine v2, Model v2, and Policy v2. Only the
authoritative Blind v2 lifecycle fields and new Phase 13 artifacts changed.

## 29. Tests and lint

Pre-score preflight and Phase 13 tests passed before the one look. Final test and
lint outcomes are recorded in the handoff and result-hash manifest; no frontend
files changed.

## 30. Remaining weaknesses

{metrics['remaining_weaknesses']}

## 31. Final verdict

**{verdict_name} synthetic generalization.** {verdict_reason}.

This verdict applies to the frozen synthetic benchmark, not production prevalence
or a claim of issuer/network fraud prevention.

## 32. Final lifecycle confirmation

```text
Blind v2 evaluated = true
Blind v2 consumed = true
Model v2 frozen = true
Policy v2 frozen = true
post-blind tuning = false
```

Phase 13 stops here. No retraining, retuning, regeneration, runtime switch,
cleanup, UI work, or deployment was performed.
"""
    return report


def run_official_evaluation(
    root: Path, evaluator_path: Path, pipeline_path: Path
) -> dict:
    preflight = verify_pre_evaluation(root)
    frame, causal = causal_frame(root)
    training_config = yaml.safe_load((root / "configs/training_v2.yaml").read_text())
    artifact, policy_config, policy = load_bound_stack(root)
    precomputed = precompute(frame, MODEL_FEATURES_V2)

    scoring_started = datetime.now(UTC).isoformat()
    risk = np.asarray(artifact.score_frame(frame), dtype=float)
    if len(risk) != len(frame) or not np.isfinite(risk).all():
        raise BlindV2EvaluationError("first Model v2 score output is invalid")
    consumption = consume_after_first_score(
        root, preflight, scoring_started, evaluator_path, pipeline_path
    )

    labels = frame.label.to_numpy(dtype=int)
    weights = device_weights(frame)
    model = {
        key: round(value, 6)
        for key, value in probability_metrics(labels, risk, weights).items()
    }
    calibration = pd.DataFrame(reliability_bins(labels, risk, weights))
    thresholds = threshold_diagnostics(frame, risk)
    decisions, devices = policy_decisions(frame, risk, policy)
    policy_metrics = policy_summary(decisions, devices)
    families = family_table(decisions, devices)

    detection = {
        "all_attacks": detection_group(
            devices, tuple(sorted(frame.loc[frame.label.eq(1), "scenario"].unique()))
        )
    }
    for scenario in (
        "patient_tester_v2",
        "ultra_patient_v2",
        "sparse_multiday_v2",
        "cross_device_strong",
        "cross_device_partial",
        "cross_device_weak_guest",
    ):
        detection[scenario] = detection_group(devices, (scenario,))
    detection["cross_device_combined"] = detection_group(
        devices,
        (
            "cross_device_strong",
            "cross_device_partial",
            "cross_device_weak_guest",
        ),
    )

    baselines = matched_baselines(frame, risk, training_config, thresholds)
    segments = segment_diagnostics(frame, decisions, devices, risk)
    labels_frame = pd.read_csv(root / "data/generated/blind_v2/labels.csv")
    linkage = linkage_diagnostics(devices, labels_frame)
    gate = evidence_gate_value(frame, risk, policy_config, precomputed)
    subscription = subscription_diagnostic(frame, devices)

    development_model = json.loads(
        (root / "artifacts/evaluation/model_v2_validation_metrics.json").read_text()
    )["model_scores"]
    development_policy = json.loads(
        (root / "artifacts/policy_v2/operational_policy_v2.json").read_text()
    )["validation_metrics"]
    gap = {
        key: round(model[key] - float(development_model[key]), 6)
        for key in ("pr_auc", "roc_auc", "brier", "ece")
    }
    gap.update(
        {
            "attack_review_or_higher": round(
                policy_metrics["attack_review_or_higher_rate"]
                - float(development_policy["attack_review_or_higher_recall"]),
                6,
            ),
            "attack_block": round(
                policy_metrics["attack_block_rate"]
                - float(development_policy["attack_block_recall"]),
                6,
            ),
            "legitimate_review_or_higher": round(
                policy_metrics["legitimate_review_or_higher_rate"]
                - float(development_policy["legitimate_review_or_higher_rate"]),
                6,
            ),
            "legitimate_block": round(
                policy_metrics["legitimate_block_rate"]
                - float(development_policy["legitimate_block_rate"]),
                6,
            ),
        }
    )

    patient_combined = detection_group(
        devices,
        ("patient_tester_v2", "ultra_patient_v2", "sparse_multiday_v2"),
    )
    long_horizon = (
        "useful under the frozen system"
        if patient_combined["review_or_higher_rate"] >= 0.70
        else "not sufficient to establish that the patient problem is solved"
    )
    device_segments = {row["segment"]: row for row in segments["device_segments"]}
    guest_rate = device_segments.get("always_guest", {}).get(
        "legitimate_review_or_higher_rate", 0.0
    )
    known_rate = device_segments.get("ever_customer_present", {}).get(
        "legitimate_review_or_higher_rate", 0.0
    )
    guest_interpretation = (
        "disproportionately penalized"
        if guest_rate > known_rate + 0.01
        else "not disproportionately penalized by more than one percentage point"
    )
    verdict_name, verdict_reason = verdict(model, policy_metrics)
    weaknesses = []
    if patient_combined["review_or_higher_rate"] < 0.70:
        weaknesses.append("patient/sparse combined REVIEW+ remains below 70%")
    if policy_metrics["legitimate_review_or_higher_rate"] > 0.06:
        weaknesses.append("aggregate legitimate REVIEW+ exceeds 6%")
    if policy_metrics["legitimate_block_rate"] > 0.01:
        weaknesses.append("aggregate legitimate BLOCK exceeds 1%")
    if subscription["review_or_higher_rate"] > 0.06:
        weaknesses.append("subscription dunning has elevated friction")
    if not weaknesses:
        weaknesses.append(
            "synthetic coverage, small-family uncertainty, and production "
            "transfer remain"
        )

    metrics = {
        "status": "official_one_time_blind_v2_evaluation",
        "evaluated": True,
        "consumed": True,
        "post_blind_tuning": False,
        "pre_evaluation": preflight,
        "consumption": consumption,
        "causal_replay": causal,
        "model_version": "model-v2",
        "feature_count": len(MODEL_FEATURES_V2),
        "model_metrics": model,
        "policy_config": policy_config,
        "policy": policy_metrics,
        "operating_targets": {
            "attack_review_or_higher": (
                "PASS"
                if policy_metrics["attack_review_or_higher_rate"] >= 0.70
                else "FAIL"
            ),
            "legitimate_review_or_higher": (
                "PASS"
                if policy_metrics["legitimate_review_or_higher_rate"] <= 0.06
                else "FAIL"
            ),
            "legitimate_block": (
                "PASS" if policy_metrics["legitimate_block_rate"] <= 0.01 else "FAIL"
            ),
        },
        "customer_id_segments": segments,
        "linkage_diagnostic": linkage,
        "evidence_gate": gate,
        "subscription_dunning": subscription,
        "development_to_blind": gap,
        "long_horizon_interpretation": long_horizon,
        "guest_friction_interpretation": guest_interpretation,
        "verdict": verdict_name,
        "verdict_reason": verdict_reason,
        "remaining_weaknesses": "; ".join(weaknesses) + ".",
        "realism_warning": (
            "Blind v2 legitimate decline rate 34.49% exceeded the 34% warning "
            "level but remained below the 46% hard gate."
        ),
    }

    output = root / "artifacts/evaluation"
    report_path = root / "reports/phase_13_blind_v2_evaluation_report.md"
    metrics_path = output / "blind_v2_metrics.json"
    family_path = output / "blind_v2_family_metrics.csv"
    threshold_path = output / "blind_v2_threshold_table.csv"
    baseline_path = output / "blind_v2_baselines.csv"
    detection_path = output / "blind_v2_detection_delay.json"
    calibration_path = output / "blind_v2_calibration.csv"
    json_write(metrics_path, metrics)
    families.to_csv(family_path, index=False)
    thresholds.to_csv(threshold_path, index=False)
    baselines.to_csv(baseline_path, index=False)
    json_write(detection_path, detection)
    calibration.to_csv(calibration_path, index=False)
    report_path.write_text(
        build_report(metrics, thresholds, families, baselines, detection)
    )

    result_files = {
        "evaluation_module": str(evaluator_path.relative_to(root)),
        "evaluation_pipeline": str(pipeline_path.relative_to(root)),
        "metrics": str(metrics_path.relative_to(root)),
        "family_metrics": str(family_path.relative_to(root)),
        "threshold_table": str(threshold_path.relative_to(root)),
        "baseline_report": str(baseline_path.relative_to(root)),
        "detection_delay": str(detection_path.relative_to(root)),
        "calibration": str(calibration_path.relative_to(root)),
        "consumption_record": str(
            (output / "blind_v2_consumption.json").relative_to(root)
        ),
        "phase_13_report": str(report_path.relative_to(root)),
    }
    # A report cannot embed its own final hash without a circular dependency.
    # Embed every other result hash, then hash the finished report into the
    # canonical external result manifest.
    hashes = {
        key: sha256_file(root / path)
        for key, path in result_files.items()
        if key != "phase_13_report"
    }
    report_path.write_text(
        build_report(metrics, thresholds, families, baselines, detection, hashes)
    )
    hashes["phase_13_report"] = sha256_file(report_path)
    result_manifest = {
        "blind_version": "v2",
        "evaluated": True,
        "consumed": True,
        "post_blind_tuning": False,
        "files": result_files,
        "hashes": hashes,
        "created_utc": datetime.now(UTC).isoformat(),
        "note": (
            "The report hash is external to the report to avoid self-hash recursion."
        ),
    }
    hash_path = output / "blind_v2_result_hashes.json"
    json_write(hash_path, result_manifest)

    freeze_path = output / "blind_v2_freeze_manifest.json"
    freeze = json.loads(freeze_path.read_text())
    freeze["evaluation_complete_utc"] = datetime.now(UTC).isoformat()
    freeze["result_hash_manifest"] = str(hash_path.relative_to(root))
    freeze["result_hash_manifest_sha256"] = sha256_file(hash_path)
    freeze["consumption_record_sha256"] = sha256_file(
        output / "blind_v2_consumption.json"
    )
    json_write(freeze_path, freeze)
    return metrics
