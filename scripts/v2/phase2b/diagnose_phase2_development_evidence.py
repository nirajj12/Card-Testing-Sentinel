"""Gate G: development-only diagnostic analysis (Phase 2B).

Reads ONLY already-known development evidence: the frozen training OOF
predictions, the frozen calibrated model, the frozen rules engine, and the
training+validation *development* populations (the Phase 2 validation set was
already inspected and executed once; the freeze/access ledger prove it, and
this script's own comment and outputs never describe anything computed here as
"fresh validation performance" -- it is development diagnosis of a closed,
blocked experiment).

Writes only to artifacts/v2/phase2b/diagnostics/ and reports/v2/phase2b/ --
new namespaces. Never modifies any historical Phase 2 artifact, never trains
anything, never creates a Phase 2B freeze or a blind challenge.
"""

from __future__ import annotations

import json

import joblib
import numpy as np
import pandas as pd

from card_testing_sentinel.v2.evaluation.access import (
    ROOT,
    load_training_features,
    open_validation,
    verify_training_freeze,
)
from card_testing_sentinel.v2.policy.rules import MAX_RULE_SCORE, evaluate_rules

DIAG_DIR = ROOT / "artifacts/v2/phase2b/diagnostics"
DIAG_DIR.mkdir(parents=True, exist_ok=True)

RULE_FEATURE_KEYS = (
    "prospective_requests_60s",
    "prior_attempts_5m",
    "distinct_cards_24h",
    "prior_decline_streak",
    "card_switches_after_decline_24h",
    "sessions_7d",
    "prior_attempts_7d",
    "requests_per_ip_5m",
    "near_minimum_ratio_24h",
)

KEY_FEATURES_FOR_COMPARISON = (
    "prospective_requests_60s",
    "prior_attempts_5m",
    "distinct_cards_24h",
    "prior_decline_streak",
    "card_switches_after_decline_24h",
    "sessions_7d",
    "requests_per_ip_5m",
    "near_minimum_ratio_24h",
    "same_card_retry_ratio_24h",
)


def _rule_scores(frame: pd.DataFrame) -> pd.Series:
    records = frame[list(RULE_FEATURE_KEYS)].to_dict("records")
    scores = [evaluate_rules(r)[0] for r in records]
    return pd.Series(scores, index=frame.index, name="rule_score")


def device_authorization_counts(
    train_events: pd.DataFrame, val_events: pd.DataFrame
) -> pd.DataFrame:
    rows = []
    for split_name, frame in (("train", train_events), ("validation", val_events)):
        grouped = frame.groupby(["population", "scenario_tag", "label"])
        for (population, scenario, label), sub in grouped:
            rows.append(
                {
                    "split": split_name,
                    "population": population,
                    "scenario_tag": scenario,
                    "label": int(label),
                    "device_count": sub["device_id"].nunique(),
                    "authorization_event_count": len(sub),
                }
            )
    return pd.DataFrame(rows).sort_values(["split", "population", "scenario_tag"])


def score_distribution_table(
    oof: pd.DataFrame, val_scored: pd.DataFrame
) -> pd.DataFrame:
    rows = []
    for split_name, frame, _raw_col, cal_col in (
        ("train_oof", oof, "raw_probability", "calibrated_probability"),
        (
            "validation_development",
            val_scored,
            "raw_probability",
            "calibrated_probability",
        ),
    ):
        device_level = frame.groupby(["device_id", "scenario_tag"], as_index=False).agg(
            max_raw=("raw_probability", "max"),
            max_calibrated=(cal_col, "max"),
        )
        for scenario, sub in device_level.groupby("scenario_tag"):
            rows.append(
                {
                    "split": split_name,
                    "scenario_tag": scenario,
                    "device_count": len(sub),
                    "max_raw_p10": sub["max_raw"].quantile(0.10),
                    "max_raw_p50": sub["max_raw"].quantile(0.50),
                    "max_raw_p90": sub["max_raw"].quantile(0.90),
                    "max_calibrated_p10": sub["max_calibrated"].quantile(0.10),
                    "max_calibrated_p50": sub["max_calibrated"].quantile(0.50),
                    "max_calibrated_p90": sub["max_calibrated"].quantile(0.90),
                }
            )
    return pd.DataFrame(rows).sort_values(["split", "scenario_tag"])


def fp_fn_by_scenario(
    oof: pd.DataFrame, val_scored: pd.DataFrame, threshold: float
) -> pd.DataFrame:
    rows = []
    for split_name, frame in (
        ("train_oof", oof),
        ("validation_development", val_scored),
    ):
        device_level = frame.groupby(
            ["device_id", "scenario_tag", "label"], as_index=False
        ).agg(max_calibrated=("calibrated_probability", "max"))
        device_level["predicted_positive"] = device_level["max_calibrated"] >= threshold
        for scenario, sub in device_level.groupby("scenario_tag"):
            label = sub["label"].iloc[0]
            n = len(sub)
            flagged = int(sub["predicted_positive"].sum())
            if label == 1:
                fn = int((~sub["predicted_positive"]).sum())
                rows.append(
                    {
                        "split": split_name,
                        "scenario_tag": scenario,
                        "population_label": "attacker",
                        "device_count": n,
                        "flagged_review_or_block": flagged,
                        "never_flagged_false_negative": fn,
                    }
                )
            else:
                fp = flagged
                rows.append(
                    {
                        "split": split_name,
                        "scenario_tag": scenario,
                        "population_label": "legitimate",
                        "device_count": n,
                        "flagged_review_or_block": flagged,
                        "false_positive_count": fp,
                    }
                )
    return pd.DataFrame(rows).sort_values(["split", "scenario_tag"])


def feature_distribution_comparison(
    train_events: pd.DataFrame, val_events: pd.DataFrame
) -> pd.DataFrame:
    rows = []
    for split_name, frame in (("train", train_events), ("validation", val_events)):
        for scenario, sub in frame.groupby("scenario_tag"):
            row = {"split": split_name, "scenario_tag": scenario, "row_count": len(sub)}
            for feat in KEY_FEATURES_FOR_COMPARISON:
                row[f"{feat}_median"] = float(sub[feat].median())
                row[f"{feat}_p90"] = float(sub[feat].quantile(0.90))
            rows.append(row)
    return pd.DataFrame(rows).sort_values(["scenario_tag", "split"])


def grouped_oof_metrics_by_fold_and_scenario(oof: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (fold, scenario), sub in oof.groupby(["fold", "scenario_tag"]):
        label = sub["label"].iloc[0]
        if label == 1:
            recall_at_05 = float((sub["calibrated_probability"] >= 0.5).mean())
            rows.append(
                {
                    "fold": int(fold),
                    "scenario_tag": scenario,
                    "label": "attacker",
                    "row_count": len(sub),
                    "recall_at_0.5": recall_at_05,
                    "mean_calibrated_probability": float(
                        sub["calibrated_probability"].mean()
                    ),
                }
            )
        else:
            fpr_at_05 = float((sub["calibrated_probability"] >= 0.5).mean())
            rows.append(
                {
                    "fold": int(fold),
                    "scenario_tag": scenario,
                    "label": "legitimate",
                    "row_count": len(sub),
                    "false_positive_rate_at_0.5": fpr_at_05,
                    "mean_calibrated_probability": float(
                        sub["calibrated_probability"].mean()
                    ),
                }
            )
    return pd.DataFrame(rows).sort_values(["scenario_tag", "fold"])


def calibration_reliability(frame: pd.DataFrame, label_source: str) -> pd.DataFrame:
    device_level = frame.groupby(["device_id"], as_index=False).agg(
        max_calibrated=("calibrated_probability", "max"),
        label=("label", "max"),
    )
    bins = np.linspace(0, 1, 11)
    device_level["bin"] = pd.cut(
        device_level["max_calibrated"], bins, include_lowest=True
    )
    grouped = device_level.groupby("bin", observed=True).agg(
        device_count=("label", "size"),
        mean_predicted=("max_calibrated", "mean"),
        observed_attacker_rate=("label", "mean"),
    )
    grouped["source"] = label_source
    return grouped.reset_index()


def rules_vs_ml_failure_analysis(
    oof: pd.DataFrame,
    val_scored: pd.DataFrame,
    rule_threshold_review: int,
    ml_threshold_review: float,
) -> pd.DataFrame:
    rows = []
    for split_name, frame in (
        ("train_oof", oof),
        ("validation_development", val_scored),
    ):
        device_level = frame.groupby(
            ["device_id", "scenario_tag", "label"], as_index=False
        ).agg(
            max_calibrated=("calibrated_probability", "max"),
            max_rule_score=("rule_score", "max"),
        )
        device_level["ml_flags"] = device_level["max_calibrated"] >= ml_threshold_review
        device_level["rules_flag"] = (
            device_level["max_rule_score"] >= rule_threshold_review
        )
        for scenario, sub in device_level.groupby("scenario_tag"):
            label = sub["label"].iloc[0]
            rows.append(
                {
                    "split": split_name,
                    "scenario_tag": scenario,
                    "label": "attacker" if label == 1 else "legitimate",
                    "device_count": len(sub),
                    "rules_only_flagged": int(
                        (sub["rules_flag"] & ~sub["ml_flags"]).sum()
                    ),
                    "ml_only_flagged": int(
                        (sub["ml_flags"] & ~sub["rules_flag"]).sum()
                    ),
                    "both_flagged": int((sub["rules_flag"] & sub["ml_flags"]).sum()),
                    "neither_flagged": int(
                        (~sub["rules_flag"] & ~sub["ml_flags"]).sum()
                    ),
                }
            )
    return pd.DataFrame(rows).sort_values(["split", "scenario_tag"])


def main() -> None:
    freeze = verify_training_freeze()  # fails closed if the evidence chain has drifted
    train_events = load_training_features()
    val_features, _val_raw, _access = open_validation()

    oof = pd.read_csv(ROOT / "artifacts/v2/predictions/training_oof_predictions.csv")

    model_meta = json.loads(
        (ROOT / "artifacts/v2/models/model_metadata.json").read_text()
    )
    model = joblib.load(ROOT / "artifacts/v2/models/calibrated_model.joblib")

    val_scored = val_features.copy()
    val_scored["raw_probability"] = model.predict_raw_proba(val_scored)
    val_scored["calibrated_probability"] = model.predict_proba(val_scored)

    train_events["rule_score"] = _rule_scores(train_events)
    val_scored["rule_score"] = _rule_scores(val_scored)
    oof = oof.merge(train_events[["event_id", "rule_score"]], on="event_id", how="left")

    device_authorization_counts(train_events, val_scored).to_csv(
        DIAG_DIR / "device_authorization_counts.csv", index=False
    )
    score_distribution_table(oof, val_scored).to_csv(
        DIAG_DIR / "score_distributions.csv", index=False
    )
    # policy_023's frozen ML review threshold (see phase2_final_closeout.md)
    fp_fn_by_scenario(oof, val_scored, threshold=0.45).to_csv(
        DIAG_DIR / "fp_fn_by_scenario_at_review_threshold_0_45.csv", index=False
    )
    feature_distribution_comparison(train_events, val_scored).to_csv(
        DIAG_DIR / "feature_distribution_comparison.csv", index=False
    )
    grouped_oof_metrics_by_fold_and_scenario(oof).to_csv(
        DIAG_DIR / "grouped_oof_metrics_by_fold_and_scenario.csv", index=False
    )
    pd.concat(
        [
            calibration_reliability(oof, "train_oof"),
            calibration_reliability(val_scored, "validation_development"),
        ]
    ).to_csv(DIAG_DIR / "calibration_reliability_train_vs_validation.csv", index=False)
    # policy_007's frozen rules-only review score (see phase2_final_closeout.md)
    rules_vs_ml_failure_analysis(
        oof, val_scored, rule_threshold_review=4, ml_threshold_review=0.45
    ).to_csv(DIAG_DIR / "rules_vs_ml_failure_analysis.csv", index=False)

    summary = {
        "training_freeze_sha256_verified": freeze is not None,
        "model_family": model_meta.get("family"),
        "max_rule_score": MAX_RULE_SCORE,
        "train_devices": int(train_events["device_id"].nunique()),
        "validation_devices": int(val_scored["device_id"].nunique()),
        "note": (
            "All scores computed here are development-only diagnosis of the "
            "already-inspected, already-blocked Phase 2 validation population. "
            "None of these numbers are, or should be cited as, fresh validation "
            "performance."
        ),
    }
    (DIAG_DIR / "diagnosis_run_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
