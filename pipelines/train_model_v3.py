"""Train Model v3 development candidates on Dataset v4.

Usage:
    python pipelines/train_model_v3.py
"""

from __future__ import annotations

import json
from pathlib import Path

from card_testing_sentinel.ml.training_v3 import train_and_evaluate_model_v3

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    dataset_path = ROOT / "data/generated/development_v4_1/features_v3_1.csv"
    config_path = ROOT / "configs/training_v3_1.yaml"
    output_dir = ROOT / "artifacts/model_v3_1"

    print("Starting Model v3 Training & Evaluation Pipeline...")
    results = train_and_evaluate_model_v3(dataset_path, config_path, output_dir)

    print("\n" + "=" * 80)
    print("CANDIDATE MODELS (5-Fold Grouped CV Out-of-Fold on TRAIN)")
    print("=" * 80)
    print(results["cand_table"].to_string(index=False))

    print("\n" + "=" * 80)
    print("CALIBRATION COMPARISON (OOF on TRAIN)")
    print("=" * 80)
    print(results["calib_table"].to_string(index=False))

    print("\n" + "=" * 80)
    print("HELD-OUT VALIDATION SET PROBABILITY METRICS (Model v3)")
    print("=" * 80)
    for k, v in results["val_metrics"].items():
        print(f"  {k:<20}: {v:.4f}")

    print("\n" + "=" * 80)
    print("COUNTERFACTUAL TWIN PAIR ORDERING (CPOA)")
    print("=" * 80)
    cf = results["cf_results"]
    print(f"  Total Twin Pairs Tested: {cf['total_pairs']}")
    print(f"  Correctly Ordered (Att Score > Legit Score): {cf['correct_pairs']}")
    print(f"  CPOA Accuracy: {cf['cpoa'] * 100:.1f}%")

    print("\n" + "=" * 80)
    print("POLICY v2 PRODUCT METRICS (HELD-OUT VALIDATION)")
    print("=" * 80)
    exp_a = results["exp_a"]
    exp_b = results["exp_b"]
    print("Experiment A (Model v3 + Unchanged Policy v2):")
    print(f"  Attack REVIEW+   : {exp_a['attack_review_plus'] * 100:.2f}% (Gate >= 70%)")
    print(f"  Attack BLOCK     : {exp_a['attack_block'] * 100:.2f}%")
    print(f"  Legitimate REVIEW+: {exp_a['legitimate_review_plus'] * 100:.2f}% (Gate <= 6%)")
    print(f"  Legitimate BLOCK : {exp_a['legitimate_block'] * 100:.2f}% (Gate <= 1%)")

    print("\nExperiment B (Model v3 + Policy v2 with Moderate Trust Suppression):")
    print(f"  Attack REVIEW+   : {exp_b['attack_review_plus'] * 100:.2f}%")
    print(f"  Attack BLOCK     : {exp_b['attack_block'] * 100:.2f}%")
    print(f"  Legitimate REVIEW+: {exp_b['legitimate_review_plus'] * 100:.2f}%")
    print(f"  Legitimate BLOCK : {exp_b['legitimate_block'] * 100:.2f}%")

    print("\n" + "=" * 80)
    print("CRITICAL SCENARIO BREAKDOWN (Validation Split)")
    print("=" * 80)
    print(f"{'Scenario':<35} | {'Devices':<7} | {'REVIEW+':<8} | {'BLOCK':<8} | {'Mean Max Score'}")
    print("-" * 80)
    for sc, metrics in sorted(exp_a["scenario_metrics"].items()):
        print(
            f"{sc:<35} | {metrics['devices']:<7} | "
            f"{metrics['review_plus_rate'] * 100:<7.1f}% | "
            f"{metrics['block_rate'] * 100:<7.1f}% | "
            f"{metrics['mean_max_score']:<7.4f}"
        )

    print("\n" + "=" * 80)
    print("FEATURE FAMILY ABLATION STUDY (Validation Split)")
    print("=" * 80)
    print(results["ablation_table"].to_string(index=False))
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
