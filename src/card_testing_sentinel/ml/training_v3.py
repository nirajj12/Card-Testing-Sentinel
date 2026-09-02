"""Model v3 training, cross-validation, selection, calibration, and evaluation.

Trains on Dataset v4 TRAIN split under Feature Contract v3 (46 features).
Evaluates candidate families, calibration, ablations, counterfactual pairs,
and policy interactions on the held-out VALIDATION split.
Historical artifacts remain frozen.
"""

from __future__ import annotations

import hashlib
import json
import platform
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import sklearn
import yaml

from card_testing_sentinel.features.specification_v3 import (
    FEATURE_CONTRACT_V3_VERSION,
    MODEL_FEATURES_V3,
    MODEL_FEATURES_V3_SHA256,
)
from card_testing_sentinel.ml.calibration import (
    apply_calibrator,
    fit_calibrator,
)
from card_testing_sentinel.ml.candidates_v3 import (
    CandidateV3,
    build_model_v3,
    candidate_grid_v3,
    fit_model_v3,
    fitted_feature_names_v3,
    predict_v3,
)
from card_testing_sentinel.ml.folds_v3 import group_audit, make_leakage_group_folds
from card_testing_sentinel.ml.metrics import (
    balanced_training_weights,
    device_weights,
    probability_metrics,
    reliability_bins,
)
from card_testing_sentinel.policy.engine_v2 import RiskPolicyV2
from card_testing_sentinel.policy.evidence_v2 import evidence_codes_v2

NON_FEATURE_COLUMNS = (
    "request_id",
    "device_id",
    "actor_id",
    "leakage_group_id",
    "customer_id",
    "session_id",
    "timestamp",
    "split",
    "label",
    "population",
    "scenario",
    "merchant_id",
    "merchant_kind",
    "counterfactual_pair_id",
    "counterfactual_role",
)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _training_weights(frame: pd.DataFrame) -> np.ndarray:
    """Equal device/class weights with a stable effective sample mass.

    The shared v2 helper intentionally sums to one. That scale makes sklearn
    regularization depend on dataset size and caused the old C=5 discontinuity.
    Keep v2 frozen and rescale only Model v3.1 weights to one unit per device.
    """
    return balanced_training_weights(frame) * frame.device_id.nunique()


@dataclass
class RiskModelArtifactV3:
    model: object
    family: str
    parameters: dict
    calibration_method: str
    calibrator: object | None
    feature_names: tuple[str, ...]
    feature_contract_sha256: str
    feature_contract_version: str
    interactions: tuple[tuple[str, str], ...] = ()

    def score_frame(self, frame: pd.DataFrame) -> np.ndarray:
        cand = CandidateV3(
            identifier="runtime",
            family=self.family,
            parameters=self.parameters,
            features=self.feature_names,
            interactions=self.interactions,
        )
        raw = predict_v3(self.model, cand, frame)
        return apply_calibrator(self.calibration_method, self.calibrator, raw)


def evaluate_candidate_oof(
    candidate: CandidateV3,
    train_frame: pd.DataFrame,
    folds: pd.DataFrame,
    seed: int,
) -> tuple[np.ndarray, dict[str, float]]:
    merged = train_frame.copy()
    fold_map = folds.set_index("device_id")["fold"]
    merged["fold"] = merged.device_id.map(fold_map)
    if merged.fold.isna().any():
        raise RuntimeError("some training rows have no actor-safe fold")
    n_folds = int(folds.fold.max()) + 1
    raw_scores = np.zeros(len(merged), dtype=float)

    for fold_idx in range(n_folds):
        is_val = merged.fold == fold_idx
        is_tr = ~is_val
        tr_df = merged.loc[is_tr]
        val_df = merged.loc[is_val]

        model = build_model_v3(candidate, seed + fold_idx)
        weights = _training_weights(tr_df)
        fit_model_v3(model, candidate, tr_df, tr_df.label.to_numpy(dtype=int), weights)
        raw_scores[is_val] = predict_v3(model, candidate, val_df)

    weights = device_weights(merged)
    metrics = probability_metrics(merged.label.to_numpy(dtype=int), raw_scores, weights)
    return raw_scores, metrics


def evaluate_policy_on_frame(
    frame: pd.DataFrame,
    scores: np.ndarray,
    policy_config: dict,
) -> dict[str, Any]:
    policy = RiskPolicyV2(policy_config)
    decisions: list[str] = []
    
    records = frame.to_dict("records")
    for row, score in zip(records, scores, strict=True):
        ts = row["timestamp"]
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        dec = policy.decide(
            snapshot=row,
            risk_score=float(score),
            timestamp=ts,
            campaign_active=bool(row.get("campaign_active", False)),
        )
        decisions.append(dec.action)

    frame_eval = frame.copy()
    frame_eval["score"] = scores
    frame_eval["decision"] = decisions

    # Device-level worst decision
    # block > review > allow
    rank = {"allow": 0, "review": 1, "block": 2}
    frame_eval["decision_rank"] = frame_eval["decision"].map(rank)
    dev_agg = (
        frame_eval.groupby(["device_id", "population", "scenario", "label"])
        .agg(
            max_rank=("decision_rank", "max"),
            max_score=("score", "max"),
            cf_pair=("counterfactual_pair_id", "first"),
            cf_role=("counterfactual_role", "first"),
        )
        .reset_index()
    )
    dev_agg["device_decision"] = dev_agg["max_rank"].map({0: "allow", 1: "review", 2: "block"})
    dev_agg["is_review_plus"] = dev_agg["max_rank"] >= 1
    dev_agg["is_block"] = dev_agg["max_rank"] >= 2

    # Primary product metrics
    attacks = dev_agg.loc[dev_agg.label.eq(1)]
    legit = dev_agg.loc[dev_agg.label.eq(0)]

    attack_review_plus = float(attacks["is_review_plus"].mean()) if len(attacks) > 0 else 0.0
    attack_block = float(attacks["is_block"].mean()) if len(attacks) > 0 else 0.0
    legit_review_plus = float(legit["is_review_plus"].mean()) if len(legit) > 0 else 0.0
    legit_block = float(legit["is_block"].mean()) if len(legit) > 0 else 0.0

    # Scenario breakdowns
    scenario_metrics: dict[str, dict[str, float]] = {}
    for sc, group in dev_agg.groupby("scenario"):
        scenario_metrics[sc] = {
            "devices": int(len(group)),
            "review_plus_rate": float(group["is_review_plus"].mean()),
            "block_rate": float(group["is_block"].mean()),
            "mean_max_score": float(group["max_score"].mean()),
        }

    return {
        "attack_review_plus": attack_review_plus,
        "attack_block": attack_block,
        "legitimate_review_plus": legit_review_plus,
        "legitimate_block": legit_block,
        "device_outcomes": dev_agg,
        "scenario_metrics": scenario_metrics,
    }


def evaluate_counterfactual_pairs(dev_agg: pd.DataFrame) -> dict[str, Any]:
    """Calculate Counterfactual Pair Ordering Accuracy (CPOA).
    
    A pair is correctly ordered if score(attack_twin) > score(legit_twin).
    """
    pairs = dev_agg.dropna(subset=["cf_pair"]).groupby("cf_pair")
    total_pairs = 0
    correct_order = 0
    pair_details: list[dict] = []

    for pair_id, group in pairs:
        attack_rows = group.loc[group.label.eq(1)]
        legit_rows = group.loc[group.label.eq(0)]
        if attack_rows.empty or legit_rows.empty:
            continue
        total_pairs += 1
        att_score = float(attack_rows["max_score"].mean())
        leg_score = float(legit_rows["max_score"].mean())
        correct = att_score > leg_score
        if correct:
            correct_order += 1
        pair_details.append({
            "pair_id": pair_id,
            "attack_score": att_score,
            "legit_score": leg_score,
            "margin": att_score - leg_score,
            "correct": correct,
        })

    cpoa = (correct_order / total_pairs) if total_pairs > 0 else 0.0
    return {
        "cpoa": cpoa,
        "total_pairs": total_pairs,
        "correct_pairs": correct_order,
        "pair_details": pair_details,
    }


def train_and_evaluate_model_v3(
    dataset_path: Path,
    config_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    config = yaml.safe_load(config_path.read_text())
    frame = pd.read_csv(dataset_path, low_memory=False)

    train_frame = frame.loc[frame.split.eq("train")].copy().reset_index(drop=True)
    val_frame = frame.loc[frame.split.eq("validation")].copy().reset_index(drop=True)

    # Fold assignment on train
    per_device = (
        train_frame[["device_id", "scenario", "leakage_group_id"]]
        .drop_duplicates("device_id")
        .reset_index(drop=True)
    )
    folds = make_leakage_group_folds(
        per_device,
        int(config["training"]["folds"]),
        int(config["training"]["seed"]),
    )

    # 1. Evaluate candidate grid on TRAIN out-of-fold
    candidates = candidate_grid_v3(config)
    candidate_results: list[dict] = []
    oof_scores_by_id: dict[str, np.ndarray] = {}

    print(f"Evaluating {len(candidates)} candidate models via 5-fold grouped CV...")
    for cand in candidates:
        oof_scores, metrics = evaluate_candidate_oof(
            cand, train_frame, folds, int(config["training"]["seed"])
        )
        oof_scores_by_id[cand.identifier] = oof_scores
        candidate_results.append({
            "candidate": cand.identifier,
            "family": cand.family,
            "pr_auc": metrics["pr_auc"],
            "roc_auc": metrics["roc_auc"],
            "brier": metrics["brier"],
            "ece": metrics["ece"],
            "log_loss": metrics["log_loss"],
        })

    cand_table = pd.DataFrame(candidate_results).sort_values("pr_auc", ascending=False)
    best_cand_row = cand_table.iloc[0]
    best_cand_id = best_cand_row["candidate"]
    selected_candidate = next(c for c in candidates if c.identifier == best_cand_id)
    print(f"Selected Best Candidate: {best_cand_id} (PR-AUC: {best_cand_row['pr_auc']:.4f})")

    # 2. Calibration study on selected candidate's OOF predictions
    best_oof_scores = oof_scores_by_id[best_cand_id]
    weights = device_weights(train_frame)
    y_train = train_frame.label.to_numpy(dtype=int)

    calib_rows = []
    calibrators = {}
    for method in ("none", "sigmoid", "isotonic"):
        cal = fit_calibrator(method, best_oof_scores, y_train, weights)
        calibrators[method] = cal
        cal_scores = apply_calibrator(method, cal, best_oof_scores)
        m = probability_metrics(y_train, cal_scores, weights)
        calib_rows.append({
            "method": method,
            "pr_auc": m["pr_auc"],
            "roc_auc": m["roc_auc"],
            "brier": m["brier"],
            "ece": m["ece"],
            "log_loss": m["log_loss"],
        })
    calib_table = pd.DataFrame(calib_rows)

    # Pick calibration method: sigmoid if PR-AUC loss <= tolerance, else none
    sig_row = calib_table.loc[calib_table.method.eq("sigmoid")].iloc[0]
    uncal_row = calib_table.loc[calib_table.method.eq("none")].iloc[0]
    pr_loss = uncal_row["pr_auc"] - sig_row["pr_auc"]
    chosen_method = "sigmoid" if pr_loss <= float(config["training"]["pr_auc_tolerance"]) else "none"
    chosen_calibrator = calibrators[chosen_method]

    # 3. Refit selected model on full TRAIN split
    full_model = build_model_v3(selected_candidate, int(config["training"]["seed"]))
    full_weights = _training_weights(train_frame)
    fit_model_v3(full_model, selected_candidate, train_frame, y_train, full_weights)

    artifact = RiskModelArtifactV3(
        model=full_model,
        family=selected_candidate.family,
        parameters=selected_candidate.parameters,
        calibration_method=chosen_method,
        calibrator=chosen_calibrator,
        feature_names=selected_candidate.features,
        feature_contract_sha256=MODEL_FEATURES_V3_SHA256,
        feature_contract_version=FEATURE_CONTRACT_V3_VERSION,
        interactions=selected_candidate.interactions,
    )

    # 4. Targeted ablations. Each ablation gets its own TRAIN OOF calibrator;
    # the final development-validation labels are never used for calibration.
    print("Running feature family ablations on validation split...")
    ablation_specs = config.get("ablations", {})
    ablation_results = []
    val_weights = device_weights(val_frame)
    y_val = val_frame.label.to_numpy(dtype=int)

    for ab_name, drop_features in ablation_specs.items():
        kept_features = tuple(f for f in MODEL_FEATURES_V3 if f not in drop_features)
        ab_cand = selected_candidate.with_features(kept_features, ab_name)
        ab_oof, _ = evaluate_candidate_oof(
            ab_cand, train_frame, folds, int(config["training"]["seed"])
        )
        ab_calibrator = fit_calibrator(
            chosen_method, ab_oof, y_train, device_weights(train_frame)
        )
        ab_model = build_model_v3(ab_cand, int(config["training"]["seed"]))
        fit_model_v3(ab_model, ab_cand, train_frame, y_train, full_weights)
        ab_raw = predict_v3(ab_model, ab_cand, val_frame)
        ab_cal = apply_calibrator(chosen_method, ab_calibrator, ab_raw)
        m = probability_metrics(y_val, ab_cal, val_weights)
        policy_metrics = evaluate_policy_on_frame(
            val_frame, ab_cal, {
                "family": "evidence_gated_v2", "review_threshold": 0.75,
                "block_threshold": 0.90, "block_evidence": 2,
                "evidence_set": "v2_full", "trust_suppression": "none",
                "block_ttl_seconds": 3600, "campaign_review_increment": 0.0,
                "campaign_block_increment": 0.0,
                "degraded_review_rule_score": 4, "degraded_block_rule_score": 6,
            }
        )
        ablation_results.append({
            "ablation": ab_name,
            "dropped_count": len(drop_features),
            "remaining_features": len(kept_features),
            "pr_auc": m["pr_auc"],
            "roc_auc": m["roc_auc"],
            "brier": m["brier"],
            "ece": m["ece"],
            "attack_review_plus": policy_metrics["attack_review_plus"],
            "attack_block": policy_metrics["attack_block"],
            "legitimate_review_plus": policy_metrics["legitimate_review_plus"],
            "legitimate_block": policy_metrics["legitimate_block"],
            "scenario_metrics": policy_metrics["scenario_metrics"],
        })
    ablation_table = pd.DataFrame([
        {k: v for k, v in row.items() if k != "scenario_metrics"}
        for row in ablation_results
    ])

    # 5. Evaluate Model v3 on held-out VALIDATION split
    val_raw_scores = predict_v3(full_model, selected_candidate, val_frame)
    val_scores = apply_calibrator(chosen_method, chosen_calibrator, val_raw_scores)
    val_metrics = probability_metrics(y_val, val_scores, val_weights)

    # 6. Evaluate Counterfactual Twin Pairs
    val_frame_with_scores = val_frame.copy()
    val_frame_with_scores["score"] = val_scores
    dev_agg_val = (
        val_frame_with_scores.groupby(["device_id", "population", "scenario", "label"])
        .agg(
            max_score=("score", "max"),
            cf_pair=("counterfactual_pair_id", "first"),
            cf_role=("counterfactual_role", "first"),
        )
        .reset_index()
    )
    cf_results = evaluate_counterfactual_pairs(dev_agg_val)

    # 7. Policy Experiments on VALIDATION: Policy v2 unchanged vs Moderate Trust
    policy_v2_unchanged = {
        "family": "evidence_gated_v2",
        "review_threshold": 0.75,
        "block_threshold": 0.90,
        "block_evidence": 2,
        "evidence_set": "v2_full",
        "trust_suppression": "none",
        "block_ttl_seconds": 3600,
        "campaign_review_increment": 0.0,
        "campaign_block_increment": 0.0,
        "degraded_review_rule_score": 4,
        "degraded_block_rule_score": 6,
    }
    policy_v2_moderate_trust = dict(policy_v2_unchanged, trust_suppression="moderate")

    exp_a = evaluate_policy_on_frame(val_frame, val_scores, policy_v2_unchanged)
    exp_b = evaluate_policy_on_frame(val_frame, val_scores, policy_v2_moderate_trust)

    # 8. Freeze Model v3 artifacts
    joblib.dump(artifact, output_dir / "risk_model_v3_1.joblib")
    
    metadata = {
        "model_version": config["model_version"],
        "development_evidence_status": "corrected-actor-safe",
        "supersedes": "rejected model-v3 development evidence",
        "provenance": {
            "dataset_features_sha256": _sha256_file(dataset_path),
            "training_config_sha256": _sha256_file(config_path),
            "feature_config_sha256": _sha256_file(
                config_path.parents[0] / "features_v3_1.yaml"
            ),
            "generator_source_sha256": _sha256_file(
                config_path.parents[0].parent
                / "src/card_testing_sentinel/ml/generator_v4.py"
            ),
        },
        "feature_contract": {
            "version": FEATURE_CONTRACT_V3_VERSION,
            "sha256": MODEL_FEATURES_V3_SHA256,
            "feature_count": len(MODEL_FEATURES_V3),
            "features": list(MODEL_FEATURES_V3),
        },
        "selected_candidate": {
            "identifier": selected_candidate.identifier,
            "family": selected_candidate.family,
            "parameters": selected_candidate.parameters,
            "interactions": [list(p) for p in selected_candidate.interactions],
            "fitted_features": fitted_feature_names_v3(selected_candidate),
        },
        "calibration": {
            "method": chosen_method,
            "pr_auc_loss": float(pr_loss),
            "table": calib_table.to_dict(orient="records"),
        },
        "validation_metrics": val_metrics,
        "counterfactual_pair_accuracy": cf_results["cpoa"],
        "policy_experiments": {
            "experiment_a_unchanged_policy_v2": {
                "attack_review_plus": exp_a["attack_review_plus"],
                "attack_block": exp_a["attack_block"],
                "legitimate_review_plus": exp_a["legitimate_review_plus"],
                "legitimate_block": exp_a["legitimate_block"],
            },
            "experiment_b_moderate_trust": {
                "attack_review_plus": exp_b["attack_review_plus"],
                "attack_block": exp_b["attack_block"],
                "legitimate_review_plus": exp_b["legitimate_review_plus"],
                "legitimate_block": exp_b["legitimate_block"],
            },
        },
        "scenario_performance": exp_a["scenario_metrics"],
        "ablations": ablation_results,
        "fold_group_audit": group_audit(per_device, folds),
        "environment": {
            "python_version": sys.version,
            "platform": platform.platform(),
            "sklearn_version": sklearn.__version__,
        },
    }

    (output_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))
    (output_dir / "feature_contract.json").write_text(
        json.dumps({
            "version": FEATURE_CONTRACT_V3_VERSION,
            "sha256": MODEL_FEATURES_V3_SHA256,
            "features": list(MODEL_FEATURES_V3),
        }, indent=2)
    )
    cand_table.to_csv(output_dir / "candidate_metrics.csv", index=False)
    calib_table.to_csv(output_dir / "calibration_metrics.csv", index=False)
    folds.to_csv(output_dir / "actor_safe_folds.csv", index=False)
    (output_dir / "targeted_ablations.json").write_text(
        json.dumps(ablation_results, indent=2)
    )
    scored = val_frame[[
        "request_id", "device_id", "actor_id", "leakage_group_id", "scenario",
        "population", "label", "counterfactual_pair_id", "counterfactual_role",
    ]].copy()
    scored["score"] = val_scores
    scored.to_csv(output_dir / "development_validation_scores.csv", index=False)

    return {
        "artifact": artifact,
        "metadata": metadata,
        "cand_table": cand_table,
        "calib_table": calib_table,
        "ablation_table": ablation_table,
        "val_metrics": val_metrics,
        "cf_results": cf_results,
        "exp_a": exp_a,
        "exp_b": exp_b,
    }
