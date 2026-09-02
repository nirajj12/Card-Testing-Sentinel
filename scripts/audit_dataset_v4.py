"""Run Dataset v4 Audit and print formatted diagnostic verification tables.

Usage:
    python scripts/audit_dataset_v4.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import yaml

from card_testing_sentinel.ml.validation_v4 import audit_dataset_v4

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data/generated/development_v4_1"
CONFIG_PATH = ROOT / "configs/dataset_v4_1.yaml"


def main() -> int:
    if not (DATA_DIR / "features_v3_1.csv").exists():
        print(f"Error: {DATA_DIR / 'features_v3_1.csv'} does not exist. Run pipelines/generate_dataset_v4.py first.")
        return 1

    print("Loading Dataset v4 artifacts...")
    raw = pd.read_csv(DATA_DIR / "raw_events.csv")
    labels = pd.read_csv(DATA_DIR / "labels.csv")
    features = pd.read_csv(DATA_DIR / "features_v3_1.csv")
    config = yaml.safe_load(CONFIG_PATH.read_text())

    print("Running Dataset v4 Audit & Shortcut Guardrail verification...")
    report = audit_dataset_v4(raw, labels, features, config)

    print("\n" + "=" * 80)
    print("DATASET v4 AUDIT REPORT SUMMARY")
    print("=" * 80)
    print(f"Total Events: {len(raw)}")
    print(f"Total Requests: {report.summary['total_requests']}")
    print(f"Total Devices: {report.summary['total_devices']}")
    print(f"Attack Prevalence: {report.summary['base_prevalence']:.4f}")
    print(f"Audit Status: {'PASSED' if report.passed else 'FAILED'}")

    if report.failures:
        print("\nHARD FAILURES ENCOUNTERED:")
        for fail in report.failures:
            print(f"  [X] {fail}")

    print("\nCRITICAL SCENARIO DEVICE COVERAGE (Minimum 250 Target):")
    crit_scenarios = [
        "cross_device_weak_guest",
        "cross_device_partial",
        "distributed_bot_campaign",
        "subscription_dunning_hard",
        "persistent_card_problem_hard",
        "network_retry_storm_hard",
        "shared_household_device",
        "cgnat_mobile_ip_storm",
    ]
    for sc in crit_scenarios:
        cnt = report.summary["device_counts_by_scenario"].get(sc, 0)
        status = "OK" if cnt >= 250 else "BELOW_QUOTA"
        print(f"  - {sc:<32}: {cnt:>4} devices [{status}]")

    print("\nSINGLE-FEATURE PR-AUC AUDIT TABLE:")
    print(f"{'Feature Name':<35} | {'PR-AUC':<7} | {'ROC-AUC':<7} | {'Lift':<5} | {'Stab':<6} | {'Diagnostic Status'}")
    print("-" * 80)
    for row in report.summary["single_feature_audit"]:
        print(
            f"{row['feature']:<35} | {row['pr_auc']:<7.4f} | {row['roc_auc']:<7.4f} | "
            f"{row['lift_over_prevalence']:<5.2f} | {row['train_val_stability_delta']:<6.4f} | "
            f"{row['diagnostic_verdict']}"
        )

    print("=" * 80 + "\n")
    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
