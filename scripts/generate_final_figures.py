"""Generate Phase 5A figures from committed aggregate evidence only."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

os.environ.setdefault(
    "MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "card-testing-sentinel-mpl")
)
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker as mticker  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "artifacts/figures"
GENERATION_SCRIPT = "scripts/generate_final_figures.py"
SOURCES = {
    "metrics": "artifacts/evaluation/pbrss_v1_metrics.json",
    "family": "artifacts/evaluation/pbrss_v1_family_metrics.csv",
    "delay": "artifacts/evaluation/pbrss_v1_detection_delay.json",
    "calibration": "artifacts/evaluation/pbrss_v1_calibration.csv",
    "shift": "artifacts/analysis/phase_4a_ordinary_checkout_feature_shift.csv",
    "latency": "artifacts/runtime/phase_4c_precheck_latency.json",
    "economics": "artifacts/economics/phase_4d_economic_scenarios.json",
}

BLUE = "#2367A8"
ORANGE = "#E58A2B"
TEAL = "#168C86"
INK = "#17212B"
MUTED = "#65717D"
GRID = "#D9E0E6"
NEGATIVE = "#C44E52"
POSITIVE = "#2A7F62"

SCENARIO_LABELS = {
    "stealth_low_amount_drip": "Stealth low-amount\nattack",
    "hybrid_credential_stuffing_probe": "Hybrid credential\nprobe",
    "mixed_card_probe": "Mixed-card\nprobe",
    "charity_micro_donation_spike": "Charity spike",
    "b2b_multi_corporate_card": "B2B corporate-card\ntraffic",
    "ordinary_checkout": "Ordinary checkout",
}
ECONOMIC_LABELS = {
    "quiet_day": "Quiet day",
    "active_attack_campaign": "Active attack\ncampaign",
    "high_value_merchant": "High-value\nmerchant",
}


def _configure_style() -> None:
    plt.rcParams.update(
        {
            "figure.dpi": 140,
            "savefig.dpi": 180,
            "font.family": "DejaVu Sans",
            "font.size": 11,
            "axes.titlesize": 17,
            "axes.titleweight": "bold",
            "axes.labelsize": 11,
            "axes.labelcolor": INK,
            "axes.edgecolor": GRID,
            "axes.linewidth": 0.8,
            "xtick.color": MUTED,
            "ytick.color": MUTED,
            "legend.frameon": False,
        }
    )


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def load_calibration(path: Path) -> list[dict[str, float]] | None:
    """Load committed calibration bins, or safely decline if they are absent."""
    if not path.exists():
        return None
    required = {"mean_predicted", "observed_rate", "weight"}
    rows = _read_csv(path)
    if not rows or not required.issubset(rows[0]):
        return None
    return [
        {
            "mean_predicted": float(row["mean_predicted"]),
            "observed_rate": float(row["observed_rate"]),
            "weight": float(row["weight"]),
        }
        for row in rows
    ]


def load_frozen_inputs(
    root: Path = ROOT, calibration_override: Path | None = None
) -> dict[str, Any]:
    """Read only committed aggregate reporting artifacts."""
    paths = {name: root / relative for name, relative in SOURCES.items()}
    family_rows = _read_csv(paths["family"])
    attack = [row for row in family_rows if int(row["label"]) == 1]
    legitimate = [row for row in family_rows if int(row["label"]) == 0]
    delay_payload = _read_json(paths["delay"])
    shift_rows = sorted(
        _read_csv(paths["shift"]), key=lambda row: float(row["psi"]), reverse=True
    )[:10]
    calibration_path = calibration_override or paths["calibration"]
    return {
        "paths": paths,
        "metrics": _read_json(paths["metrics"]),
        "attack_scenarios": [
            {
                "scenario": row["scenario"],
                "review_plus_pct": float(row["reviewed"]) * 100,
                "block_pct": float(row["blocked"]) * 100,
            }
            for row in attack
        ],
        "legitimate_scenarios": [
            {
                "scenario": row["scenario"],
                "review_plus_pct": float(row["reviewed"]) * 100,
                "block_pct": float(row["blocked"]) * 100,
            }
            for row in legitimate
        ],
        "detection_delay": [
            {"attempt": int(attempt), "surfaced_pct": float(rate) * 100}
            for attempt, rate in delay_payload.items()
            if attempt.isdigit()
        ],
        "calibration": load_calibration(calibration_path),
        "calibration_path": calibration_path,
        "feature_shift": [
            {"feature": row["feature"], "psi": float(row["psi"])} for row in shift_rows
        ],
        "latency": _read_json(paths["latency"]),
        "economics": _read_json(paths["economics"]),
    }


def _clean_axes(ax: plt.Axes, *, grid_axis: str = "y") -> None:
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis=grid_axis, color=GRID, linewidth=0.8, alpha=0.7)
    ax.set_axisbelow(True)


def _footer(fig: plt.Figure, text: str) -> None:
    fig.text(0.01, 0.015, text, ha="left", va="bottom", fontsize=8.5, color=MUTED)


def _save(fig: plt.Figure, path: Path) -> None:
    fig.savefig(
        path,
        bbox_inches="tight",
        facecolor="white",
        metadata={"Software": "Card-Testing Sentinel Phase 5A"},
    )
    plt.close(fig)


def plot_attack_performance(rows: list[dict[str, Any]], path: Path) -> None:
    narrative_order = [
        "stealth_low_amount_drip",
        "hybrid_credential_stuffing_probe",
        "mixed_card_probe",
    ]
    by_scenario = {row["scenario"]: row for row in rows}
    rows = [by_scenario[name] for name in narrative_order]
    labels = [SCENARIO_LABELS[row["scenario"]] for row in rows]
    review = [row["review_plus_pct"] for row in rows]
    block = [row["block_pct"] for row in rows]
    positions = list(range(len(rows)))
    width = 0.34
    fig, ax = plt.subplots(figsize=(10, 6.2))
    bars_review = ax.bar(
        [value - width / 2 for value in positions],
        review,
        width,
        label="REVIEW+",
        color=BLUE,
    )
    bars_block = ax.bar(
        [value + width / 2 for value in positions],
        block,
        width,
        label="BLOCK",
        color=ORANGE,
        hatch="//",
    )
    ax.bar_label(bars_review, labels=[f"{value:.1f}%" for value in review], padding=3)
    ax.bar_label(bars_block, labels=[f"{value:.1f}%" for value in block], padding=3)
    ax.set_title("Attack coverage across shifted stress scenarios", loc="left", pad=18)
    ax.set_ylabel("Attack device profiles (%)")
    ax.set_xticks(positions, labels)
    ax.set_ylim(0, 112)
    ax.legend(ncols=2, loc="upper right")
    _clean_axes(ax)
    _footer(fig, "Frozen PBRSS-v1 device-level results • Synthetic stress evaluation")
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    _save(fig, path)


def plot_detection_delay(rows: list[dict[str, Any]], path: Path) -> None:
    rows = sorted(rows, key=lambda row: row["attempt"])
    attempts = [row["attempt"] for row in rows]
    values = [row["surfaced_pct"] for row in rows]
    fig, ax = plt.subplots(figsize=(10, 5.8))
    ax.plot(attempts, values, color=BLUE, linewidth=3, marker="o", markersize=9)
    for attempt, value in zip(attempts, values, strict=True):
        ax.annotate(
            f"{value:.1f}%",
            (attempt, value),
            xytext=(0, 11),
            textcoords="offset points",
            ha="center",
            color=INK,
            fontweight="bold",
        )
    ax.axvspan(0.75, 2.25, color=ORANGE, alpha=0.09)
    ax.text(1.5, 8, "Limited behavioral history", ha="center", color=MUTED)
    ax.set_title("Behavioral history drives detection", loc="left", pad=18)
    ax.set_xlabel("Attempt number")
    ax.set_ylabel("Cumulative attack profiles surfaced (%)")
    ax.set_xticks(attempts)
    ax.set_xlim(0.75, 5.25)
    ax.set_ylim(0, 108)
    _clean_axes(ax)
    _footer(
        fig,
        "No attempt-4 value is inferred • Frozen PBRSS-v1 device-level results",
    )
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    _save(fig, path)


def plot_legitimate_friction(rows: list[dict[str, Any]], path: Path) -> None:
    order = [
        "charity_micro_donation_spike",
        "b2b_multi_corporate_card",
        "ordinary_checkout",
    ]
    by_scenario = {row["scenario"]: row for row in rows}
    rows = [by_scenario[name] for name in order]
    labels = [SCENARIO_LABELS[row["scenario"]] for row in rows]
    review = [row["review_plus_pct"] for row in rows]
    block = [row["block_pct"] for row in rows]
    positions = list(range(len(rows)))
    width = 0.34
    fig, ax = plt.subplots(figsize=(10, 6.2))
    review_bars = ax.bar(
        [value - width / 2 for value in positions],
        review,
        width,
        label="REVIEW+",
        color=BLUE,
    )
    block_bars = ax.bar(
        [value + width / 2 for value in positions],
        block,
        width,
        label="BLOCK",
        color=ORANGE,
        hatch="//",
    )
    ax.bar_label(review_bars, labels=[f"{value:.1f}%" for value in review], padding=3)
    ax.bar_label(block_bars, labels=[f"{value:.2f}%" for value in block], padding=3)
    ax.set_title("Where legitimate-user friction concentrates", loc="left", pad=18)
    ax.set_ylabel("Legitimate device profiles (%)")
    ax.set_xticks(positions, labels)
    ax.set_ylim(0, 30)
    ax.legend(ncols=2, loc="upper left")
    _clean_axes(ax)
    _footer(fig, "Frozen PBRSS-v1 device-level results • REVIEW+ includes BLOCK")
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    _save(fig, path)


def plot_calibration(
    rows: list[dict[str, float]], metrics: dict[str, Any], path: Path
) -> None:
    predicted = [row["mean_predicted"] for row in rows]
    observed = [row["observed_rate"] for row in rows]
    weights = [row["weight"] for row in rows]
    max_weight = max(weights)
    sizes = [45 + 180 * weight / max_weight for weight in weights]
    fig, ax = plt.subplots(figsize=(8, 7))
    ax.plot([0, 1], [0, 1], linestyle="--", color=MUTED, label="Ideal calibration")
    ax.plot(predicted, observed, color=BLUE, linewidth=2, alpha=0.8)
    ax.scatter(
        predicted,
        observed,
        s=sizes,
        color=BLUE,
        edgecolor="white",
        linewidth=1.2,
        label="PBRSS-v1 bins",
        zorder=3,
    )
    ax.set_title("Calibration under shifted stress traffic", loc="left", pad=18)
    ax.text(
        0,
        1.025,
        f"Brier {metrics['brier']:.3f}  •  ECE {metrics['ece']:.3f}",
        transform=ax.transAxes,
        color=MUTED,
    )
    ax.set_xlabel("Mean predicted risk")
    ax.set_ylabel("Observed attack rate")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_aspect("equal", adjustable="box")
    ax.legend(loc="lower right")
    _clean_axes(ax)
    _footer(fig, "Point area reflects bin weight • Frozen PBRSS-v1 calibration bins")
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    _save(fig, path)


def _readable_feature(name: str) -> str:
    return name.replace("_", " ")


def plot_feature_shift(rows: list[dict[str, Any]], path: Path) -> None:
    rows = sorted(rows, key=lambda row: row["psi"])
    labels = [_readable_feature(row["feature"]) for row in rows]
    values = [row["psi"] for row in rows]
    fig, ax = plt.subplots(figsize=(10, 7.2))
    bars = ax.barh(labels, values, color=TEAL)
    ax.bar_label(bars, labels=[f"{value:.2f}" for value in values], padding=5)
    ax.set_title(
        "Top covariate shifts in ordinary checkout traffic", loc="left", pad=18
    )
    ax.set_xlabel("Population Stability Index (PSI)")
    ax.set_xlim(0, max(values) * 1.14)
    _clean_axes(ax, grid_axis="x")
    _footer(
        fig,
        "PSI measures distribution shift; it does not prove causal feature attribution",
    )
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    _save(fig, path)


def plot_latency(payload: dict[str, Any], path: Path) -> None:
    labels = ["p50", "p90", "p95", "p99"]
    values = [float(payload["latency_ms"][name]) for name in labels]
    fig, ax = plt.subplots(figsize=(9, 5.8))
    bars = ax.bar(labels, values, color=[BLUE, BLUE, ORANGE, ORANGE])
    ax.bar_label(bars, labels=[f"{value:.1f} ms" for value in values], padding=4)
    ax.set_title("Local /api/precheck latency", loc="left", pad=18)
    ax.set_ylabel("Round-trip latency (milliseconds)")
    ax.set_ylim(0, max(values) * 1.2)
    _clean_axes(ax)
    _footer(
        fig,
        f"{payload['measured_requests']} sequential local requests, "
        f"{payload['errors']} errors • Local non-production benchmark",
    )
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    _save(fig, path)


def _format_inr_axis(value: float, _position: float) -> str:
    if value == 0:
        return "INR 0"
    sign = "−" if value < 0 else ""
    return f"{sign}INR {abs(value) / 1_000_000:.1f}M"


def plot_economics(payload: dict[str, Any], path: Path) -> None:
    scenario_order = ["quiet_day", "active_attack_campaign", "high_value_merchant"]
    labels = [ECONOMIC_LABELS[name] for name in scenario_order]
    values = [
        float(payload["scenarios"][name]["net_illustrative_value_inr"])
        for name in scenario_order
    ]
    colors = [NEGATIVE if value < 0 else POSITIVE for value in values]
    fig, ax = plt.subplots(figsize=(10, 6.2))
    bars = ax.bar(labels, values, color=colors)
    ax.axhline(0, color=INK, linewidth=1.1)
    for bar, value in zip(bars, values, strict=True):
        x_position = bar.get_x() + bar.get_width() / 2
        if value < 0:
            ax.text(
                x_position,
                value / 2,
                f"−INR {abs(value) / 1_000_000:.2f}M",
                ha="center",
                va="center",
                fontweight="bold",
                color="white",
            )
        else:
            ax.annotate(
                f"INR +{value / 1_000_000:.2f}M",
                (x_position, value),
                xytext=(0, 8),
                textcoords="offset points",
                ha="center",
                va="bottom",
                fontweight="bold",
                color=INK,
            )
    ax.set_title(
        "Illustrative economics depend on merchant context", loc="left", pad=18
    )
    ax.set_ylabel("Estimated net illustrative value")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(_format_inr_axis))
    lower = min(values) * 1.45
    upper = max(values) * 1.24
    ax.set_ylim(lower, upper)
    _clean_axes(ax)
    _footer(
        fig,
        "Illustrative merchant assumptions only • Not measured Razorpay economics "
        "or observed savings",
    )
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    _save(fig, path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_records(root: Path, keys: list[str]) -> list[dict[str, str]]:
    records = []
    for key in keys:
        relative = SOURCES[key]
        records.append({"path": relative, "sha256": _sha256(root / relative)})
    return records


def _manifest_entry(
    root: Path,
    filename: str,
    title: str,
    source_keys: list[str],
    metrics: Any,
) -> dict[str, Any]:
    return {
        "filename": filename,
        "title": title,
        "source_artifacts": _source_records(root, source_keys),
        "metrics_used": metrics,
        "generation_script": GENERATION_SCRIPT,
        "generated_from_frozen_evidence": True,
        "model_rescored": False,
        "pbrss_rescored": False,
    }


def generate_final_figures(
    root: Path = ROOT,
    output_dir: Path = DEFAULT_OUTPUT,
    calibration_override: Path | None = None,
) -> dict[str, Any]:
    """Generate all supported figures and their deterministic provenance manifest."""
    _configure_style()
    output_dir.mkdir(parents=True, exist_ok=True)
    data = load_frozen_inputs(root, calibration_override)
    figures: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []

    filename = "pbrss_scenario_performance.png"
    plot_attack_performance(data["attack_scenarios"], output_dir / filename)
    figures.append(
        _manifest_entry(
            root,
            filename,
            "Attack coverage across shifted stress scenarios",
            ["family"],
            data["attack_scenarios"],
        )
    )

    filename = "pbrss_detection_delay.png"
    plot_detection_delay(data["detection_delay"], output_dir / filename)
    figures.append(
        _manifest_entry(
            root,
            filename,
            "Behavioral history drives detection",
            ["delay"],
            data["detection_delay"],
        )
    )

    filename = "pbrss_legitimate_friction.png"
    plot_legitimate_friction(data["legitimate_scenarios"], output_dir / filename)
    figures.append(
        _manifest_entry(
            root,
            filename,
            "Where legitimate-user friction concentrates",
            ["family"],
            data["legitimate_scenarios"],
        )
    )

    if data["calibration"] is None:
        skipped.append(
            {
                "filename": "pbrss_calibration.png",
                "reason": (
                    "committed calibration bins are missing or incomplete; "
                    "no rescoring attempted"
                ),
                "expected_source": str(data["calibration_path"]),
            }
        )
    else:
        filename = "pbrss_calibration.png"
        plot_calibration(data["calibration"], data["metrics"], output_dir / filename)
        figures.append(
            _manifest_entry(
                root,
                filename,
                "Calibration under shifted stress traffic",
                ["calibration", "metrics"],
                {
                    "bins": data["calibration"],
                    "brier": data["metrics"]["brier"],
                    "ece": data["metrics"]["ece"],
                },
            )
        )

    filename = "phase_4a_feature_shift.png"
    plot_feature_shift(data["feature_shift"], output_dir / filename)
    figures.append(
        _manifest_entry(
            root,
            filename,
            "Top covariate shifts in ordinary checkout traffic",
            ["shift"],
            data["feature_shift"],
        )
    )

    filename = "phase_4c_latency.png"
    plot_latency(data["latency"], output_dir / filename)
    latency_values = {
        key: data["latency"]["latency_ms"][key] for key in ("p50", "p90", "p95", "p99")
    }
    figures.append(
        _manifest_entry(
            root,
            filename,
            "Local /api/precheck latency",
            ["latency"],
            {
                **latency_values,
                "measured_requests": data["latency"]["measured_requests"],
                "errors": data["latency"]["errors"],
            },
        )
    )

    filename = "phase_4d_economic_scenarios.png"
    plot_economics(data["economics"], output_dir / filename)
    economic_values = {
        name: scenario["net_illustrative_value_inr"]
        for name, scenario in data["economics"]["scenarios"].items()
    }
    figures.append(
        _manifest_entry(
            root,
            filename,
            "Illustrative economics depend on merchant context",
            ["economics"],
            economic_values,
        )
    )

    manifest = {
        "version": "phase-5a-v1",
        "generation_script": GENERATION_SCRIPT,
        "generated_from_frozen_evidence": True,
        "model_rescored": False,
        "pbrss_rescored": False,
        "figures": figures,
        "skipped_figures": skipped,
    }
    (output_dir / "figure_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    manifest = generate_final_figures(output_dir=args.output_dir)
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
