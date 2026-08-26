"""Run isolated Phase 2B training and stop after its verified freeze."""

import argparse
import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import yaml

from card_testing_sentinel.common.atomic_io import atomic_write_json, atomic_write_text
from card_testing_sentinel.v2.phase2b.freeze_manifest import write_training_freeze
from card_testing_sentinel.v2.phase2b.training import (
    compare_reproduction,
    run_development_training,
)

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = ROOT / "configs/v2/phase2b/training.yaml"
DEFAULT_OUTPUT = ROOT / "artifacts/v2/phase2b/training"


def _report(result: dict, reproduction: dict, freeze_digest: str) -> str:
    selection = result["selection"]
    sanity = result["sanity"]
    parity = result["parity"]
    return (
        "\n".join(
            [
                "# Phase 2B training-only closeout",
                "",
                (
                    "No validation or blind population was generated or read, "
                    "and no policy was evaluated."
                ),
                "",
                (
                    f"- Selected model: `{selection['selected_candidate']}` "
                    f"({selection['selected_family']})"
                ),
                f"- Calibration: `{selection['selected_calibration']}`",
                f"- Model features: {selection['model_feature_count']}",
                (
                    f"- Serialization fixture: {result['serialization']['rows']} "
                    "rows; full OOF is recorded separately"
                ),
                (
                    f"- Online/batch parity: {parity['rows_compared']} rows × "
                    f"{parity['features_compared']} features, maximum difference "
                    f"{parity['maximum_absolute_difference']}"
                ),
                f"- Shuffled-label ROC-AUC: {sanity['shuffled_label_roc_auc']:.6f}",
                (
                    "- Strongest single feature: "
                    f"`{sanity['strongest_single_feature']['feature']}` "
                    f"F1={sanity['strongest_single_feature']['f1']:.6f}"
                ),
                (
                    "- Exact unevaluated policy grid: "
                    f"{result['policy_search']['candidate_count']} candidates"
                ),
                (
                    "- Reproduction OOF maximum difference: "
                    f"{reproduction['oof_maximum_absolute_difference']}"
                ),
                f"- Training freeze SHA-256: `{freeze_digest}`",
                "",
                (
                    "All performance values are training-only diagnostics, not "
                    "held-out or production claims."
                ),
            ]
        )
        + "\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    config_path = args.config.resolve()
    output_dir = args.output_dir.resolve()
    config = yaml.safe_load(config_path.read_text())
    result = run_development_training(
        root=ROOT,
        config_path=config_path,
        output_dir=output_dir,
        log_mlflow=True,
    )
    with tempfile.TemporaryDirectory(prefix="card-testing-sentinel-v2b-repro-") as name:
        reproduction_dir = Path(name) / "training"
        run_development_training(
            root=ROOT,
            config_path=config_path,
            output_dir=reproduction_dir,
            log_mlflow=False,
        )
        reproduction = compare_reproduction(
            output_dir,
            reproduction_dir,
            float(config["probability_tolerance"]),
        )
    atomic_write_json(output_dir / "metrics/reproduction.json", reproduction)
    report_path = ROOT / "reports/v2/phase2b/training/training_closeout.md"
    eda_report_path = ROOT / "reports/v2/phase2b/eda/README.md"
    atomic_write_text(
        eda_report_path,
        "# Phase 2B training-only EDA\n\n"
        "Deterministic machine-readable tables are frozen under "
        "`artifacts/v2/phase2b/training/eda/`. No validation rows were loaded.\n",
    )
    created_utc = datetime.now(UTC).isoformat()
    protected = (
        "artifacts/v2/phase2b/training/data/training_features.csv",
        "artifacts/v2/phase2b/training/training/device_folds.csv",
        "artifacts/v2/phase2b/training/eda/eda_summary.json",
        "artifacts/v2/phase2b/training/eda/feature_summary.csv",
        "artifacts/v2/phase2b/training/eda/feature_correlations.csv",
        "artifacts/v2/phase2b/training/eda/scenario_feature_distributions.csv",
        "artifacts/v2/phase2b/training/metrics/online_batch_parity.json",
        "artifacts/v2/phase2b/training/metrics/candidate_oof_metrics.csv",
        "artifacts/v2/phase2b/training/metrics/candidate_fold_metrics.csv",
        "artifacts/v2/phase2b/training/metrics/candidate_runtime_diagnostics.csv",
        "artifacts/v2/phase2b/training/metrics/calibration_comparison.csv",
        "artifacts/v2/phase2b/training/metrics/calibration_reliability.csv",
        "artifacts/v2/phase2b/training/metrics/sanity_checks.json",
        "artifacts/v2/phase2b/training/metrics/training_selection.json",
        "artifacts/v2/phase2b/training/metrics/reproduction.json",
        "artifacts/v2/phase2b/training/metrics/mlflow_training_run.json",
        "artifacts/v2/phase2b/training/predictions/training_oof_predictions.csv",
        "artifacts/v2/phase2b/training/models/selected_model.joblib",
        "artifacts/v2/phase2b/training/models/model_feature_contract.json",
        "artifacts/v2/phase2b/training/models/model_metadata.json",
        "artifacts/v2/phase2b/training/models/serialization_fixture.csv",
        "artifacts/v2/phase2b/training/models/serialization_subprocess_predictions.json",
        "artifacts/v2/phase2b/training/policy/policy_search_space.json",
        "reports/v2/phase2b/eda/README.md",
    )
    freeze_path, digest = write_training_freeze(
        root=ROOT,
        output_dir=output_dir,
        protected_outputs=protected,
        created_utc=created_utc,
        runtime=result["runtime"],
        reproduction=reproduction,
        policy_search=result["policy_search"],
    )
    atomic_write_text(report_path, _report(result, reproduction, digest))
    summary = {
        "status": "completed",
        "freeze_path": str(freeze_path),
        "freeze_sha256": digest,
        "selection": result["selection"],
        "parity": result["parity"],
        "sanity": result["sanity"],
        "reproduction": reproduction,
        "policy_search": {
            key: result["policy_search"][key]
            for key in ("candidate_count", "family_counts", "enumeration_sha256")
        },
    }
    atomic_write_json(output_dir / "run_summary.json", summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
