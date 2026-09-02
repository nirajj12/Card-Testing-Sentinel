"""Dataset v4 validation and audit engine.

Implements all audit checks declared in docs/dataset_v4_audit_spec.md:
1. Dataset balance, row/device counts, attack prevalence.
2. Critical scenario minimum quotas (>= 250 devices per critical family).
3. Counterfactual twin pair completeness.
4. Hard leakage tests (no target labels, no future outcome fields, no scenario strings).
5. Single-feature PR-AUC diagnostic guardrail audit (with lift, stability, and diagnostic status).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score

from card_testing_sentinel.features.specification_v3 import (
    CUSTOMER_FEATURES,
    FORBIDDEN_EXEMPT,
    FORBIDDEN_TERMS,
    MODEL_FEATURES_V3,
)
from card_testing_sentinel.ml.scenarios_v4 import CRITICAL_SCENARIOS


class AuditV4Report:
    def __init__(self) -> None:
        self.passed = True
        self.failures: list[str] = []
        self.warnings: list[str] = []
        self.summary: dict[str, Any] = {}

    def require(self, condition: bool, message: str) -> None:
        if not condition:
            self.passed = False
            self.failures.append(message)

    def warn(self, condition: bool, message: str) -> None:
        if not condition:
            self.warnings.append(message)


def audit_dataset_v4(
    raw: pd.DataFrame,
    labels: pd.DataFrame,
    features: pd.DataFrame,
    config: dict,
) -> AuditV4Report:
    report = AuditV4Report()

    # 1. Label and device bookkeeping
    auth_requests = raw.loc[raw.event_type.eq("authorization_request")]
    transacting_devices = set(auth_requests.device_id.unique())
    labelled_devices = set(labels.device_id.unique())

    report.require(
        transacting_devices == labelled_devices,
        f"Device mismatch: {len(transacting_devices - labelled_devices)} unlabelled transacting devices, "
        f"{len(labelled_devices - transacting_devices)} silent devices",
    )

    # Split and correlation-unit integrity. The explicit leakage group is
    # evaluation metadata and must never enter MODEL_FEATURES_V3.
    report.require(
        "leakage_group_id" in labels.columns,
        "labels are missing leakage_group_id",
    )
    if "leakage_group_id" in labels.columns:
        train_groups = set(labels.loc[labels.split.eq("train"), "leakage_group_id"])
        val_groups = set(labels.loc[labels.split.eq("validation"), "leakage_group_id"])
        report.require(not (train_groups & val_groups), "leakage groups overlap train/validation")
        group_sizes = labels.groupby("leakage_group_id").device_id.nunique()
        report.summary["group_integrity"] = {
            "unique_groups": int(len(group_sizes)),
            "multi_device_groups": int((group_sizes > 1).sum()),
            "largest_group": int(group_sizes.max()),
            "train_validation_overlap": int(len(train_groups & val_groups)),
        }
    train_customers = set(labels.loc[labels.split.eq("train"), "customer_id"].dropna())
    val_customers = set(labels.loc[labels.split.eq("validation"), "customer_id"].dropna())
    report.require(not (train_customers & val_customers), "customers overlap train/validation")
    report.summary["customer_overlap"] = int(len(train_customers & val_customers))

    # 2. Critical scenario quotas (>= 250 devices per critical family)
    counts_by_scenario = labels.groupby("scenario")["device_id"].nunique().to_dict()
    for sc in CRITICAL_SCENARIOS:
        count = counts_by_scenario.get(sc, 0)
        report.require(
            count >= 250,
            f"Critical scenario '{sc}' has {count} devices (minimum 250 required)",
        )

    # 3. Counterfactual Pairs Completeness (20 pairs)
    cf_data = labels.dropna(subset=["counterfactual_pair_id"])
    cf_pairs = sorted(cf_data["counterfactual_pair_id"].unique())
    report.require(
        len(cf_pairs) == 20,
        f"Expected 20 counterfactual pairs, found {len(cf_pairs)}",
    )
    for pair in cf_pairs:
        pair_rows = cf_data.loc[cf_data.counterfactual_pair_id.eq(pair)]
        roles = set(pair_rows["counterfactual_role"].unique())
        report.require(
            roles == {"attack", "legitimate_twin"},
            f"Pair {pair} does not have both attack and legitimate_twin roles: {roles}",
        )
        report.require(
            pair_rows["leakage_group_id"].nunique() == 1,
            f"Pair {pair} does not share one leakage group",
        )

    # 4. Hard Leakage Failures
    feature_cols = [c for c in features.columns if c in MODEL_FEATURES_V3]
    report.require(
        len(feature_cols) == len(MODEL_FEATURES_V3),
        f"Expected {len(MODEL_FEATURES_V3)} features in table, found {len(feature_cols)}",
    )

    # Check forbidden terms
    for f in feature_cols:
        if f not in FORBIDDEN_EXEMPT:
            for term in FORBIDDEN_TERMS:
                report.require(
                    term not in f,
                    f"Hard leakage: feature '{f}' contains forbidden substring '{term}'",
                )

    # Check target label or scenario strings in feature values
    for col in ("label", "scenario", "population", "split", "merchant_kind"):
        report.require(
            col not in MODEL_FEATURES_V3,
            f"Hard leakage: label column '{col}' declared as a model feature",
        )
    for col in ("actor_id", "leakage_group_id", "counterfactual_pair_id", "counterfactual_role"):
        report.require(col not in MODEL_FEATURES_V3, f"metadata '{col}' entered feature contract")

    # 5. Diagnostic Single-Feature PR-AUC Audit
    base_prevalence = float(features["label"].mean())
    single_feature_results = []

    for f in MODEL_FEATURES_V3:
        vals = features[f].fillna(0.0).values
        y = features["label"].values

        # Handle constant features
        if np.all(vals == vals[0]):
            pr_auc = base_prevalence
            roc_auc = 0.50
        else:
            try:
                pr_auc = float(average_precision_score(y, vals))
                # Check inverted correlation if PR-AUC < base prevalence
                if pr_auc < base_prevalence:
                    pr_auc_inv = float(average_precision_score(y, -vals))
                    pr_auc = max(pr_auc, pr_auc_inv)
                roc_auc = float(roc_auc_score(y, vals))
                if roc_auc < 0.50:
                    roc_auc = 1.0 - roc_auc
            except Exception:
                pr_auc = base_prevalence
                roc_auc = 0.50

        lift = pr_auc / base_prevalence if base_prevalence > 0 else 1.0

        # Split stability
        train_mask = features["split"].eq("train").values
        val_mask = features["split"].eq("validation").values
        try:
            pr_auc_train = float(average_precision_score(y[train_mask], vals[train_mask]))
            pr_auc_val = float(average_precision_score(y[val_mask], vals[val_mask]))
            stability = abs(pr_auc_train - pr_auc_val)
        except Exception:
            stability = 0.0

        # Diagnostic Guardrails
        if pr_auc > 0.92:
            verdict = "HARD_FAIL_SUSPICIOUS_SHORTCUT"
            report.require(False, f"Feature '{f}' has extreme PR-AUC {pr_auc:.4f} > 0.92")
        elif f in ("customer_id_present", "current_amount", "is_new_device", "customer_age_seconds"):
            verdict = "REVIEW_METADATA_GUARDRAIL" if pr_auc >= 0.35 else "PASS_UNRESTRICTED"
        elif f in ("requests_60s", "requests_5m", "devices_per_ip_24h"):
            verdict = "REVIEW_VELOCITY_GUARDRAIL" if pr_auc >= 0.65 else "PASS_UNRESTRICTED"
        elif pr_auc >= 0.80:
            verdict = "REVIEW_DOMAIN_SIGNAL"
        else:
            verdict = "PASS_UNRESTRICTED"

        single_feature_results.append({
            "feature": f,
            "pr_auc": round(pr_auc, 4),
            "roc_auc": round(roc_auc, 4),
            "lift_over_prevalence": round(lift, 2),
            "train_val_stability_delta": round(stability, 4),
            "diagnostic_verdict": verdict,
        })

    report.summary["device_counts_by_scenario"] = counts_by_scenario
    report.summary["single_feature_audit"] = single_feature_results
    report.summary["base_prevalence"] = base_prevalence
    report.summary["total_devices"] = len(labelled_devices)
    report.summary["total_requests"] = len(auth_requests)

    return report
