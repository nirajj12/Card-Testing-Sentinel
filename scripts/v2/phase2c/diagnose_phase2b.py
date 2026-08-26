"""Read-only diagnosis of Phase 2B fresh-validation policy failure modes."""

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from card_testing_sentinel.common.atomic_io import atomic_write_json, atomic_write_text

ROOT = Path(__file__).resolve().parents[3]
ARTIFACTS = ROOT / "artifacts/v2/phase2c/diagnosis"
REPORTS = ROOT / "reports/v2/phase2c"
FROZEN_REVIEW_THRESHOLD = 0.35


def _quantiles(values: pd.Series) -> dict:
    return {
        "count": int(values.notna().sum()),
        "minimum": float(values.min()),
        "p10": float(values.quantile(0.10)),
        "p25": float(values.quantile(0.25)),
        "median": float(values.median()),
        "p75": float(values.quantile(0.75)),
        "p90": float(values.quantile(0.90)),
        "maximum": float(values.max()),
    }


def _maximum_consecutive(values: pd.Series, threshold: float) -> int:
    best = current = 0
    for matched in values.ge(threshold):
        current = current + 1 if matched else 0
        best = max(best, current)
    return best


def main() -> int:
    features = pd.read_csv(
        ROOT / "artifacts/v2/phase2b/validation/allow_all_features.csv"
    )
    artifact = joblib.load(
        ROOT / "artifacts/v2/phase2b/training/models/selected_model.joblib"
    )
    features["probability"] = artifact.predict_proba(features)
    features["timestamp"] = pd.to_datetime(features.timestamp, utc=True)
    features = features.sort_values(
        ["device_id", "timestamp", "event_id"], kind="mergesort"
    )
    features["request_index"] = features.groupby("device_id").cumcount() + 1

    candidate_table = pd.read_csv(
        ROOT / "artifacts/v2/phase2b/validation/policy_candidates.csv"
    )
    excess_columns = [
        name
        for name in candidate_table
        if name.endswith("review_excess_devices")
        or name.endswith("block_excess_devices")
    ]
    candidate_table["total_excess_devices"] = candidate_table[excess_columns].sum(
        axis=1
    )
    closest = {}
    for family in ("ml_only", "combined"):
        row = (
            candidate_table.loc[candidate_table.family.eq(family)]
            .sort_values(["total_excess_devices", "candidate_id"])
            .iloc[0]
        )
        closest[family] = {
            "candidate_id": row.candidate_id,
            "total_excess_devices": int(row.total_excess_devices),
            "failed_constraints": json.loads(row.failed_constraints_json),
        }

    device = (
        features.groupby("device_id", as_index=False)
        .agg(
            label=("label", "first"),
            scenario_tag=("scenario_tag", "first"),
            attack_subtype=("attack_subtype", "first"),
            maximum_score=("probability", "max"),
            mean_score=("probability", "mean"),
            high_score_count=(
                "probability",
                lambda values: int(values.ge(FROZEN_REVIEW_THRESHOLD).sum()),
            ),
            sessions=("session_id", "nunique"),
            maximum_card_switches=("card_switches_after_decline_24h", "max"),
            maximum_ip_changes=("ip_changes_24h", "max"),
            maximum_distinct_cards=("distinct_cards_14d", "max"),
            prior_checkouts=("prior_successful_checkouts", "max"),
            campaign_active=("campaign_active", "max"),
        )
        .sort_values("device_id")
    )
    consecutive = features.groupby("device_id").probability.apply(
        lambda values: _maximum_consecutive(values, FROZEN_REVIEW_THRESHOLD)
    )
    device = device.merge(
        consecutive.rename("maximum_consecutive_high").reset_index(), on="device_id"
    )
    device["persistent_high"] = device.maximum_consecutive_high.ge(2)
    device["isolated_high"] = device.high_score_count.eq(1)

    score_ranges = {}
    for dimension in ("scenario_tag", "attack_subtype"):
        score_ranges[dimension] = {
            str(name): {
                "row_scores": _quantiles(group.probability),
                "device_maximum_scores": _quantiles(
                    device.loc[
                        device[dimension].fillna("none").eq(str(name)), "maximum_score"
                    ]
                ),
            }
            for name, group in features.assign(
                **{dimension: features[dimension].fillna("none")}
            ).groupby(dimension, sort=True)
        }

    hard_negative = device.loc[
        device.scenario_tag.isin(["normal_bad_luck", "flash_hard_retry"])
        & device.maximum_score.ge(FROZEN_REVIEW_THRESHOLD)
    ]
    false_positive_evidence = {
        "definition": (
            "hard-negative device with allow-all maximum calibrated score at or "
            "above the already-frozen Phase 2B minimum ML review threshold 0.35"
        ),
        "devices": int(len(hard_negative)),
        "one_isolated_high_score": int(hard_negative.isolated_high.sum()),
        "consecutive_high_scores": int(hard_negative.persistent_high.sum()),
        "multiple_sessions": int(hard_negative.sessions.ge(2).sum()),
        "card_switching": int(hard_negative.maximum_card_switches.ge(1).sum()),
        "ip_rotation": int(hard_negative.maximum_ip_changes.ge(1).sum()),
        "no_successful_checkout_history": int(
            hard_negative.prior_checkouts.eq(0).sum()
        ),
    }

    trajectory_rows = []
    trajectory_groups = {
        "hard_negative": {"normal_bad_luck", "flash_hard_retry"},
        "evasive": {"attack_evasive"},
        "patient": {"attack_patient"},
        "burst": {"attack_burst"},
    }
    for name, scenarios in trajectory_groups.items():
        subset = features.loc[features.scenario_tag.isin(scenarios)]
        for index, group in subset.groupby("request_index", sort=True):
            trajectory_rows.append(
                {
                    "group": name,
                    "request_index": int(index),
                    "rows": len(group),
                    "mean_score": float(group.probability.mean()),
                    "median_score": float(group.probability.median()),
                    "p90_score": float(group.probability.quantile(0.9)),
                    "high_score_rate": float(
                        group.probability.ge(FROZEN_REVIEW_THRESHOLD).mean()
                    ),
                }
            )
    trajectory = pd.DataFrame(trajectory_rows)

    labels = device.label.to_numpy(dtype=int)
    persistence = {
        "maximum_score_device_roc_auc": float(
            roc_auc_score(labels, device.maximum_score)
        ),
        "mean_score_device_roc_auc": float(roc_auc_score(labels, device.mean_score)),
        "high_score_count_device_roc_auc": float(
            roc_auc_score(labels, device.high_score_count)
        ),
        "maximum_consecutive_high_device_roc_auc": float(
            roc_auc_score(labels, device.maximum_consecutive_high)
        ),
    }
    legitimate = device.loc[device.label.eq(0)]
    checkout = {
        str(name): {
            "devices": int(len(group)),
            "high_maximum_score_devices": int(
                group.maximum_score.ge(FROZEN_REVIEW_THRESHOLD).sum()
            ),
            "high_maximum_score_rate": float(
                group.maximum_score.ge(FROZEN_REVIEW_THRESHOLD).mean()
            ),
            "median_maximum_score": float(group.maximum_score.median()),
        }
        for name, group in legitimate.assign(
            checkout_history=np.where(
                legitimate.prior_checkouts.gt(0), "available", "absent"
            )
        ).groupby("checkout_history")
    }
    campaign = {
        str(bool(name)): {
            "devices": int(len(group)),
            "high_maximum_score_rate": float(
                group.maximum_score.ge(FROZEN_REVIEW_THRESHOLD).mean()
            ),
            "median_maximum_score": float(group.maximum_score.median()),
        }
        for name, group in legitimate.groupby("campaign_active")
    }
    corroboration = {
        "persistent_plus_card_diversity": int(
            (device.persistent_high & device.maximum_distinct_cards.ge(3)).sum()
        ),
        "persistent_plus_card_switch": int(
            (device.persistent_high & device.maximum_card_switches.ge(1)).sum()
        ),
        "persistent_plus_ip_rotation": int(
            (device.persistent_high & device.maximum_ip_changes.ge(1)).sum()
        ),
        "persistent_plus_multiple_sessions": int(
            (device.persistent_high & device.sessions.ge(2)).sum()
        ),
    }
    payload = {
        "scope": "read-only Phase 2B diagnosis; not policy threshold selection",
        "frozen_reference_threshold": FROZEN_REVIEW_THRESHOLD,
        "closest_infeasible": closest,
        "score_ranges": score_ranges,
        "false_positive_evidence": false_positive_evidence,
        "risk_persistence": persistence,
        "successful_checkout_history": checkout,
        "campaign_context": campaign,
        "causal_corroboration_counts": corroboration,
        "conclusions": [
            "ML-only failure is concentrated in normal_bad_luck review counts; "
            "single-row score thresholds cannot distinguish transient retry risk.",
            "Persistence, session/card/IP corroboration, checkout history, and "
            "campaign context are valid causal policy hypotheses, but all numeric "
            "choices must be selected on training-only grouped OOF replay.",
        ],
    }
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    atomic_write_json(ARTIFACTS / "phase2b_policy_diagnosis.json", payload)
    atomic_write_text(
        ARTIFACTS / "score_trajectories.csv",
        trajectory.to_csv(index=False, float_format="%.12g", lineterminator="\n"),
    )
    lines = [
        "# Phase 2B policy diagnosis for Phase 2C",
        "",
        "This is read-only diagnosis of existing Phase 2B evidence, not "
        "threshold tuning.",
        "",
        f"- Closest ML-only excess: {closest['ml_only']}",
        f"- Closest combined excess: {closest['combined']}",
        f"- Hard-negative high-score evidence: {false_positive_evidence}",
        f"- Device-level persistence comparison: {persistence}",
        f"- Checkout-history comparison: {checkout}",
        f"- Campaign comparison: {campaign}",
        "",
        "Policy hypotheses carried forward: repeated risk, corroborating causal "
        "card/IP/",
        "session evidence, decaying accumulation, successful-checkout protection, and",
        "campaign-aware evidence requirements. Scenario labels are not live inputs.",
    ]
    atomic_write_text(REPORTS / "phase2b_policy_diagnosis.md", "\n".join(lines) + "\n")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
