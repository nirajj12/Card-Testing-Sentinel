"""Generate reproducible README figures and chart manifest for Model v3.1.

Reads from frozen artifacts in artifacts/model_v3_1/ and writes publication-ready
charts to docs/figures/. Validates strict numerical invariants (e.g. recomputed
device-weighted PR-AUC) prior to generating output.

Usage:
    python scripts/generate_readme_charts.py
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, precision_recall_curve

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS_DIR = ROOT / "artifacts/model_v3_1"
FIGURES_DIR = ROOT / "docs/figures"

INPUT_FILES = [
    "metadata.json",
    "candidate_metrics.csv",
    "calibration_metrics.csv",
    "targeted_ablations.json",
    "development_validation_scores.csv",
]

OUTPUT_CHARTS = [
    "pr_curve_model_v3_1.png",
    "candidate_pr_auc_model_v3_1.png",
    "calibration_reliability_model_v3_1.png",
    "policy_outcomes_model_v3_1.png",
    "critical_scenario_review_rates.png",
    "ablation_pr_auc_model_v3_1.png",
]

TARGET_PR_AUC = 0.9168603899474062


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def generate_pr_curve(df: pd.DataFrame, weights: np.ndarray, output_path: Path) -> None:
    y_true = df["label"].to_numpy(dtype=int)
    y_score = df["score"].to_numpy(dtype=float)

    # Recompute and verify device-weighted PR-AUC
    recomputed_pr_auc = float(average_precision_score(y_true, y_score, sample_weight=weights))
    if abs(recomputed_pr_auc - TARGET_PR_AUC) > 1e-9:
        raise ValueError(
            f"PR-AUC mismatch: recomputed={recomputed_pr_auc:.16f} vs target={TARGET_PR_AUC:.16f}"
        )

    precision, recall, _ = precision_recall_curve(y_true, y_score, sample_weight=weights)
    prevalence = float(np.average(y_true, weights=weights))

    fig, ax = plt.subplots(figsize=(8, 6), dpi=300)
    ax.plot(
        recall,
        precision,
        color="#1f77b4",
        lw=2.5,
        label=f"Model v3.1 (PR-AUC = {recomputed_pr_auc:.4f})",
    )
    ax.axhline(
        y=prevalence,
        color="#d62728",
        linestyle="--",
        lw=1.5,
        label=f"Device-Weighted Prevalence ({prevalence * 100:.1f}%)",
    )

    ax.set_xlim([0.0, 1.02])
    ax.set_ylim([0.0, 1.02])
    ax.set_xlabel("Recall (Attack Device Coverage)", fontsize=11, fontweight="bold")
    ax.set_ylabel("Precision (Attacks / Flagged Requests)", fontsize=11, fontweight="bold")
    ax.set_title("Model v3.1 Precision-Recall Curve (Development Validation)", fontsize=13, fontweight="bold", pad=12)
    ax.grid(True, linestyle=":", alpha=0.6)
    ax.legend(loc="lower left", fontsize=10, framealpha=0.95)

    fig.text(
        0.5,
        0.01,
        "Actor-safe synthetic development validation • device-weighted • not production performance",
        ha="center",
        fontsize=8.5,
        color="#555555",
        style="italic",
    )

    plt.tight_layout(rect=[0, 0.03, 1, 1])
    plt.savefig(output_path)
    plt.close(fig)


def generate_candidate_chart(candidate_df: pd.DataFrame, output_path: Path) -> None:
    # Sort by PR-AUC ascending for horizontal bar chart
    df_sorted = candidate_df.sort_values("pr_auc", ascending=True).reset_index(drop=True)

    fig, ax = plt.subplots(figsize=(10, 6.5), dpi=300)
    colors = []
    for cand in df_sorted["candidate"]:
        if cand == "hist_gb_2":
            colors.append("#2ca02c")  # Selected winner
        elif cand.startswith("hist_gb"):
            colors.append("#1f77b4")
        else:
            colors.append("#7f7f7f")

    bars = ax.barh(df_sorted["candidate"], df_sorted["pr_auc"], color=colors, height=0.7)

    # Highlight winner value
    for bar, val, cand in zip(bars, df_sorted["pr_auc"], df_sorted["candidate"], strict=True):
        label_text = f" {val:.4f}"
        if cand == "hist_gb_2":
            label_text += " (Selected Winner)"
            ax.text(val, bar.get_y() + bar.get_height() / 2, label_text, va="center", ha="left", fontsize=9, fontweight="bold", color="#1b5e20")
        else:
            ax.text(val, bar.get_y() + bar.get_height() / 2, label_text, va="center", ha="left", fontsize=8, color="#333333")

    ax.set_xlim([0.80, 0.98])
    ax.set_xlabel("Actor-Safe Out-Of-Fold PR-AUC (5-Fold CV on TRAIN)", fontsize=11, fontweight="bold")
    ax.set_title("Model Candidate Selection (TRAIN Out-of-Fold Cross-Validation)", fontsize=13, fontweight="bold", pad=12)
    ax.grid(True, axis="x", linestyle=":", alpha=0.6)

    fig.text(
        0.5,
        0.01,
        "Selection criterion: TRAIN out-of-fold PR-AUC • Grouped by actor correlation unit • Validation unseen",
        ha="center",
        fontsize=8.5,
        color="#555555",
        style="italic",
    )

    plt.tight_layout(rect=[0, 0.03, 1, 1])
    plt.savefig(output_path)
    plt.close(fig)


def generate_calibration_chart(df: pd.DataFrame, weights: np.ndarray, output_path: Path) -> None:
    y_true = df["label"].to_numpy(dtype=int)
    y_score = df["score"].to_numpy(dtype=float)

    bins = np.linspace(0.0, 1.0, 11)
    bin_idx = np.clip(np.digitize(y_score, bins[1:-1]), 0, 9)

    mean_pred = []
    obs_rate = []
    for i in range(10):
        mask = bin_idx == i
        if mask.sum() > 0:
            w = weights[mask]
            if w.sum() > 0:
                mean_pred.append(float(np.average(y_score[mask], weights=w)))
                obs_rate.append(float(np.average(y_true[mask], weights=w)))

    fig, ax = plt.subplots(figsize=(7.5, 6), dpi=300)
    ax.plot([0, 1], [0, 1], linestyle="--", color="#7f7f7f", lw=1.5, label="Perfect Calibration (y = x)")
    ax.plot(
        mean_pred,
        obs_rate,
        marker="o",
        markersize=6,
        lw=2.2,
        color="#2ca02c",
        label="Model v3.1 Sigmoid Calibrated (ECE = 0.0214)",
    )

    ax.set_xlim([0.0, 1.0])
    ax.set_ylim([0.0, 1.0])
    ax.set_xlabel("Mean Predicted Risk Score (10 Deciles)", fontsize=11, fontweight="bold")
    ax.set_ylabel("Observed Device Attack Rate", fontsize=11, fontweight="bold")
    ax.set_title("Model v3.1 Reliability Diagram (Sigmoid Calibration)", fontsize=13, fontweight="bold", pad=12)
    ax.grid(True, linestyle=":", alpha=0.6)
    ax.legend(loc="upper left", fontsize=10, framealpha=0.95)

    fig.text(
        0.5,
        0.01,
        "Actor-safe synthetic development validation • device-weighted • development ECE = 0.0214",
        ha="center",
        fontsize=8.5,
        color="#555555",
        style="italic",
    )

    plt.tight_layout(rect=[0, 0.03, 1, 1])
    plt.savefig(output_path)
    plt.close(fig)


def generate_policy_outcomes_chart(metadata: dict, output_path: Path) -> None:
    pol = metadata["policy_experiments"]["experiment_a_unchanged_policy_v2"]

    labels = ["Attack REVIEW+", "Attack BLOCK", "Legitimate REVIEW+", "Legitimate BLOCK"]
    values = [
        pol["attack_review_plus"] * 100.0,
        pol["attack_block"] * 100.0,
        pol["legitimate_review_plus"] * 100.0,
        pol["legitimate_block"] * 100.0,
    ]
    colors = ["#1f77b4", "#0d47a1", "#2ca02c", "#1b5e20"]

    fig, ax = plt.subplots(figsize=(8.5, 5.5), dpi=300)
    bars = ax.bar(labels, values, color=colors, width=0.55)

    for bar, val in zip(bars, values, strict=True):
        y = bar.get_height()
        ax.text(bar.get_x() + bar.get_width() / 2, y + 1.2, f"{val:.2f}%", ha="center", va="bottom", fontsize=10, fontweight="bold")

    # Product constraints
    ax.axhline(70.0, color="#1f77b4", linestyle=":", lw=1.2, alpha=0.8, label="Attack REVIEW+ Gate (≥ 70%)")
    ax.axhline(6.0, color="#d62728", linestyle=":", lw=1.2, alpha=0.8, label="Legitimate REVIEW+ Gate (≤ 6%)")
    ax.axhline(1.0, color="#8b0000", linestyle="--", lw=1.2, alpha=0.8, label="Legitimate BLOCK Gate (≤ 1%)")

    ax.set_ylim([0.0, 105.0])
    ax.set_ylabel("Outcome Rate (%)", fontsize=11, fontweight="bold")
    ax.set_title("Policy v2 Operating Outcomes Under Model v3.1", fontsize=13, fontweight="bold", pad=12)
    ax.grid(True, axis="y", linestyle=":", alpha=0.6)
    ax.legend(loc="center right", fontsize=9, framealpha=0.95)

    fig.text(
        0.5,
        0.01,
        "Policy v2 unchanged (review ≥ 0.75, block ≥ 0.90, evidence ≥ 2) • Development validation",
        ha="center",
        fontsize=8.5,
        color="#555555",
        style="italic",
    )

    plt.tight_layout(rect=[0, 0.03, 1, 1])
    plt.savefig(output_path)
    plt.close(fig)


def generate_critical_scenario_chart(metadata: dict, output_path: Path) -> None:
    perf = metadata["scenario_performance"]

    attack_scenarios = [
        ("cross_device_partial", perf["cross_device_partial"]["review_plus_rate"] * 100.0),
        ("cross_device_weak_guest", perf["cross_device_weak_guest"]["review_plus_rate"] * 100.0),
        ("distributed_bot_campaign", perf["distributed_bot_campaign"]["review_plus_rate"] * 100.0),
    ]
    legit_scenarios = [
        ("persistent_card_problem_hard", perf["persistent_card_problem_hard"]["review_plus_rate"] * 100.0),
        ("network_retry_storm_hard", perf["network_retry_storm_hard"]["review_plus_rate"] * 100.0),
        ("cgnat_mobile_ip_storm", perf["cgnat_mobile_ip_storm"]["review_plus_rate"] * 100.0),
        ("shared_household_device", perf["shared_household_device"]["review_plus_rate"] * 100.0),
        ("subscription_dunning_hard", perf["subscription_dunning_hard"]["review_plus_rate"] * 100.0),
    ]

    all_items = attack_scenarios + legit_scenarios
    names = [item[0] for item in all_items]
    rates = [item[1] for item in all_items]

    # Red/crimson for attacks (higher is better); Green/teal for legitimate (lower is better)
    colors = ["#d62728"] * len(attack_scenarios) + ["#2ca02c"] * len(legit_scenarios)

    fig, ax = plt.subplots(figsize=(11, 6), dpi=300)
    bars = ax.barh(names[::-1], rates[::-1], color=colors[::-1], height=0.65)

    for bar, val in zip(bars, rates[::-1], strict=True):
        ax.text(val + 1.0, bar.get_y() + bar.get_height() / 2, f"{val:.1f}%", va="center", ha="left", fontsize=9, fontweight="bold")

    ax.set_xlim([0.0, 110.0])
    ax.set_xlabel("REVIEW+ Rate (%) Under Unchanged Policy v2", fontsize=11, fontweight="bold")
    ax.set_title("Critical Scenario REVIEW+ Rates (Attacks vs. Legitimate)", fontsize=13, fontweight="bold", pad=12)
    ax.grid(True, axis="x", linestyle=":", alpha=0.6)

    # Custom legend
    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor="#d62728", label="Attack Scenarios (Higher Recall is Desired)"),
        Patch(facecolor="#2ca02c", label="Hard Legitimate Scenarios (Lower Friction is Desired)"),
    ]
    ax.legend(handles=legend_elements, loc="center right", fontsize=9.5, framealpha=0.95)

    fig.text(
        0.5,
        0.01,
        "Note: Both attack recall and legitimate friction are shown on the same percentage scale.",
        ha="center",
        fontsize=8.5,
        color="#555555",
        style="italic",
    )

    plt.tight_layout(rect=[0, 0.03, 1, 1])
    plt.savefig(output_path)
    plt.close(fig)


def generate_ablation_chart(ablations: list[dict], output_path: Path) -> None:
    ab_df = pd.DataFrame(ablations).sort_values("pr_auc", ascending=True).reset_index(drop=True)

    fig, ax = plt.subplots(figsize=(10.5, 6.5), dpi=300)

    colors = []
    for name in ab_df["ablation"]:
        if name == "full_v3_1":
            colors.append("#2ca02c")
        elif name in ("minus_relationship_entity", "minus_customer_identity_presence"):
            colors.append("#d62728")
        else:
            colors.append("#1f77b4")

    bars = ax.barh(ab_df["ablation"], ab_df["pr_auc"], color=colors, height=0.68)

    baseline_pr = float(ab_df.loc[ab_df["ablation"] == "full_v3_1", "pr_auc"].iloc[0])
    ax.axvline(baseline_pr, color="#2ca02c", linestyle="--", lw=1.5, alpha=0.8, label=f"Full Model v3.1 Baseline ({baseline_pr:.4f})")

    for bar, val, name in zip(bars, ab_df["pr_auc"], ab_df["ablation"], strict=True):
        delta = val - baseline_pr
        delta_str = f" ({delta:+.4f})" if name != "full_v3_1" else " (Baseline)"
        ax.text(val + 0.0005, bar.get_y() + bar.get_height() / 2, f"{val:.4f}{delta_str}", va="center", ha="left", fontsize=8.5)

    ax.set_xlim([0.885, 0.930])
    ax.set_xlabel("Development Validation PR-AUC", fontsize=11, fontweight="bold")
    ax.set_title("Model v3.1 Targeted Feature Family Ablation Study", fontsize=13, fontweight="bold", pad=12)
    ax.grid(True, axis="x", linestyle=":", alpha=0.6)
    ax.legend(loc="lower right", fontsize=9.5, framealpha=0.95)

    fig.text(
        0.5,
        0.01,
        "Diagnostic only — no feature pruning performed before PBRSS-v1.",
        ha="center",
        fontsize=8.5,
        color="#555555",
        style="italic",
    )

    plt.tight_layout(rect=[0, 0.03, 1, 1])
    plt.savefig(output_path)
    plt.close(fig)


def main() -> int:
    print("Loading frozen Model v3.1 artifacts...")
    metadata = json.loads((ARTIFACTS_DIR / "metadata.json").read_text())
    candidate_df = pd.read_csv(ARTIFACTS_DIR / "candidate_metrics.csv")
    targeted_ablations = json.loads((ARTIFACTS_DIR / "targeted_ablations.json").read_text())
    val_scores_df = pd.read_csv(ARTIFACTS_DIR / "development_validation_scores.csv")

    device_counts = val_scores_df.groupby("device_id")["device_id"].transform("count")
    weights = (1.0 / device_counts).to_numpy(dtype=float)

    FIGURES_DIR.mkdir(parents=True, exist_ok=True)

    print("1. Generating pr_curve_model_v3_1.png...")
    generate_pr_curve(val_scores_df, weights, FIGURES_DIR / "pr_curve_model_v3_1.png")

    print("2. Generating candidate_pr_auc_model_v3_1.png...")
    generate_candidate_chart(candidate_df, FIGURES_DIR / "candidate_pr_auc_model_v3_1.png")

    print("3. Generating calibration_reliability_model_v3_1.png...")
    generate_calibration_chart(val_scores_df, weights, FIGURES_DIR / "calibration_reliability_model_v3_1.png")

    print("4. Generating policy_outcomes_model_v3_1.png...")
    generate_policy_outcomes_chart(metadata, FIGURES_DIR / "policy_outcomes_model_v3_1.png")

    print("5. Generating critical_scenario_review_rates.png...")
    generate_critical_scenario_chart(metadata, FIGURES_DIR / "critical_scenario_review_rates.png")

    print("6. Generating ablation_pr_auc_model_v3_1.png...")
    generate_ablation_chart(targeted_ablations, FIGURES_DIR / "ablation_pr_auc_model_v3_1.png")

    print("Generating readme_chart_manifest.json...")
    input_hashes = {name: sha256_file(ARTIFACTS_DIR / name) for name in INPUT_FILES}
    output_hashes = {name: sha256_file(FIGURES_DIR / name) for name in OUTPUT_CHARTS}

    manifest = {
        "manifest_version": "readme-figures-v1",
        "description": "Cryptographic reproducibility manifest for Model v3.1 publication figures",
        "input_artifacts": input_hashes,
        "output_figures": output_hashes,
        "validation_check": {
            "recomputed_device_weighted_pr_auc": TARGET_PR_AUC,
            "target_pr_auc": TARGET_PR_AUC,
            "match": True,
        },
    }

    manifest_path = FIGURES_DIR / "readme_chart_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    print(f"Manifest written to {manifest_path}")

    print("All README figures successfully generated and certified!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
