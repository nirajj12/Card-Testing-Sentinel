"""Run the guarded, non-overwriting final test evaluation exactly once."""

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

import joblib
import matplotlib
import mlflow
import yaml

from card_testing_sentinel.common.config import load_config
from card_testing_sentinel.common.exceptions import SentinelError
from card_testing_sentinel.common.logging import configure_logging
from card_testing_sentinel.data.validation import sha256_file
from card_testing_sentinel.evaluation.final_test import (
    guard_final_test,
    load_test_view_after_guard,
)
from card_testing_sentinel.evaluation.metrics import classification_metrics
from card_testing_sentinel.modeling.weights import evaluation_weights
from card_testing_sentinel.policy.selection import evaluate_policy
from card_testing_sentinel.rules.baseline import score_rules

matplotlib.use("Agg")
from matplotlib import pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def _write_json_once(payload: dict, path: Path) -> None:
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent)
    with os.fdopen(handle, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "configs/base.yaml")
    parser.add_argument(
        "--training-config", type=Path, default=ROOT / "configs/training.yaml"
    )
    parser.add_argument(
        "--policy-config", type=Path, default=ROOT / "configs/policy.yaml"
    )
    parser.add_argument(
        "--policy", type=Path, default=ROOT / "artifacts/policy/frozen_policy.json"
    )
    parser.add_argument("--confirm-final-evaluation", action="store_true")
    args = parser.parse_args()
    artifacts = ROOT / "artifacts"
    figures = ROOT / "reports/figures"
    try:
        settings = load_config(args.config)
        configure_logging(settings)
        policy = guard_final_test(
            confirmed=args.confirm_final_evaluation,
            settings=settings,
            policy_path=args.policy,
            training_config_path=args.training_config,
            policy_config_path=args.policy_config,
            artifacts_dir=artifacts,
            figure_dir=figures,
        )
        # This is the first point at which test rows may be loaded.
        view, cards = load_test_view_after_guard(settings)
        model = joblib.load(
            settings.paths.artifacts / "models" / policy["model_filename"]
        )
        training_config = yaml.safe_load(args.training_config.read_text())
        policy_config = yaml.safe_load(args.policy_config.read_text())
        risk = model.predict_proba(view.X)[:, 1]
        rules = score_rules(view.X, training_config)
        events = view.metadata.copy()
        events["true_label"] = view.y
        events["card_token"] = cards
        events["risk_score"] = risk
        events["rule_score"] = rules["rule_score"].to_numpy()
        events["fixed_rule_reason_codes"] = rules["reason_codes"].to_numpy()
        method_results = {}
        event_output = events.sort_values(
            ["device_id", "timestamp", "event_sequence"], kind="mergesort"
        ).reset_index(drop=True)
        for method, frozen_result in policy["comparator_results"].items():
            if frozen_result is None or not frozen_result["feasible"]:
                continue
            result = evaluate_policy(
                events, method, frozen_result["thresholds"], policy_config
            )
            method_results[method] = result
            event_output[f"{method}_action"] = result["replay"]["action"].to_numpy()
            event_output[f"{method}_reason_code"] = result["replay"][
                "policy_reason_code"
            ].to_numpy()
            event_output[f"{method}_is_first_review"] = result["replay"][
                "is_first_review"
            ].to_numpy()
            event_output[f"{method}_is_first_block"] = result["replay"][
                "is_first_block"
            ].to_numpy()
            event_output[f"{method}_potentially_prevented"] = result["replay"][
                "potentially_prevented"
            ].to_numpy()
        champion = policy["selected_policy_method"]
        event_output["authorization_position"] = method_results[champion]["replay"][
            "authorization_position"
        ].to_numpy()
        event_output["champion_is_first_review"] = method_results[champion]["replay"][
            "is_first_review"
        ].to_numpy()
        event_output["champion_is_first_block"] = method_results[champion]["replay"][
            "is_first_block"
        ].to_numpy()
        event_output["champion_potentially_prevented"] = method_results[champion][
            "replay"
        ]["potentially_prevented"].to_numpy()
        method_results[champion]["device_summary"].to_csv(
            artifacts / "predictions/final_test_device_summary.csv", index=False
        )
        event_output.to_csv(
            artifacts / "predictions/final_test_event_decisions.csv", index=False
        )
        weights = evaluation_weights(view.metadata["device_id"])
        static = classification_metrics(
            view.y, risk, float(policy["phase3_static_threshold"]), weights
        )
        serial_methods = {
            name: {
                key: value
                for key, value in result.items()
                if key not in {"replay", "device_summary"}
            }
            for name, result in method_results.items()
        }
        payload = {
            "status": "complete",
            "policy_sha256": sha256_file(args.policy),
            "model_sha256": policy["model_sha256"],
            "feature_hash": policy["feature_hash"],
            "frozen_checksums": policy["frozen_checksums"],
            "training_config_sha256": policy["training_config_sha256"],
            "policy_config_sha256": policy["policy_config_sha256"],
            "test_authorization_rows": len(view.X),
            "test_devices": int(view.metadata["device_id"].nunique()),
            "static_champion_metrics": static,
            "selected_policy_method": champion,
            "sequential_methods": serial_methods,
            "frozen_thresholds": {
                name: value["thresholds"]
                for name, value in policy["comparator_results"].items()
                if value
            },
            "replay_estimate_disclaimer": (
                "Offline upper-bound estimate assuming block_next_attempt ends the "
                "recorded sequence; not an observed causal outcome."
            ),
        }
        figures.mkdir(parents=True, exist_ok=True)
        fig, ax = plt.subplots(figsize=(6, 4))
        for name, result in method_results.items():
            within = result["metrics"]["detected_within_attempt"]
            ax.plot(
                [int(k) for k in within],
                [item["rate"] for item in within.values()],
                marker="o",
                label=name,
            )
        ax.set(
            xlabel="authorization attempt",
            ylabel="share of all attacker devices blocked",
            title="Final test detection by attempt",
        )
        ax.legend()
        fig.tight_layout()
        fig.savefig(figures / "final_test_detection_by_attempt.png", dpi=150)
        plt.close(fig)
        fig, ax = plt.subplots(figsize=(6, 4))
        for name, result in method_results.items():
            ax.scatter(
                result["budgets"]["legitimate_block"]["rate"],
                result["metrics"]["attacker_block_coverage"]["rate"],
                label=name,
                s=70,
            )
        ax.set(
            xlabel="legitimate-device ever-blocked rate",
            ylabel="attacker-device block coverage",
            title="Frozen policy final test comparison",
        )
        ax.legend()
        fig.tight_layout()
        fig.savefig(figures / "final_test_policy_comparison.png", dpi=150)
        plt.close(fig)
        _write_json_once(payload, artifacts / "metrics/final_test_metrics.json")
        os.environ.setdefault("MLFLOW_ALLOW_FILE_STORE", "true")
        mlflow.set_tracking_uri(settings.paths.mlflow.resolve().as_uri())
        mlflow.set_experiment("card-testing-sentinel-policy")
        with mlflow.start_run(run_name="one-time-final-test-evaluation"):
            mlflow.log_params(
                {
                    "policy_sha256": payload["policy_sha256"],
                    "selected_policy": champion,
                    "metric_definition_version": policy["metric_definition_version"],
                }
            )
            mlflow.log_metrics(
                {
                    "static_average_precision": static["average_precision"],
                    "static_roc_auc": static["roc_auc"],
                    "attacker_device_block_coverage": method_results[champion][
                        "metrics"
                    ]["attacker_block_coverage"]["rate"],
                }
            )
        print(f"Final test evaluation complete: rows={len(view.X)}")
        print(f"Devices={payload['test_devices']}")
        return 0
    except (OSError, ValueError, KeyError, FileExistsError, SentinelError) as exc:
        print(f"Final test evaluation refused: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
