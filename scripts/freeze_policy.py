"""Select and freeze a validation-only sequential policy."""

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

import joblib
import matplotlib
import mlflow
import numpy as np
import pandas as pd
import yaml

from card_testing_sentinel.common.config import load_config
from card_testing_sentinel.common.exceptions import PolicyEvaluationError, SentinelError
from card_testing_sentinel.common.logging import configure_logging
from card_testing_sentinel.data.loaders import load_enriched_events
from card_testing_sentinel.data.validation import sha256_file
from card_testing_sentinel.features.spec import MODEL_FEATURES
from card_testing_sentinel.modeling.data import (
    frozen_checksums,
    load_train_validation_views,
)
from card_testing_sentinel.policy.selection import select_policies, serializable_result

matplotlib.use("Agg")
from matplotlib import pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def _write_json(payload: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent)
    with os.fdopen(handle, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    os.replace(temporary, path)


def _validation_events(settings, model, predictions: pd.DataFrame) -> pd.DataFrame:
    _, validation = load_train_validation_views(settings)
    rescored = model.predict_proba(validation.X)[:, 1]
    saved = predictions["champion_probability"].to_numpy(dtype=float)
    if len(saved) != len(rescored) or not np.allclose(
        saved, rescored, atol=1e-10, rtol=0
    ):
        raise PolicyEvaluationError(
            "saved validation champion probabilities do not reproduce"
        )
    enriched = load_enriched_events(
        settings.paths.frozen_data / settings.frozen_dataset.enriched_events_filename
    )
    cards = enriched.loc[
        enriched["event_id"].isin(predictions["event_id"]), ["event_id", "card_token"]
    ]
    events = predictions.merge(cards, on="event_id", how="left", validate="one_to_one")
    events = events.rename(
        columns={
            "champion_probability": "risk_score",
            "true_label": "true_label",
            "rule_reason_codes": "fixed_rule_reason_codes",
        }
    )
    events["timestamp"] = pd.to_datetime(events["timestamp"], format="ISO8601")
    if events["card_token"].isna().any():
        raise PolicyEvaluationError(
            "validation card tokens missing for sequential metrics"
        )
    return events


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "configs/base.yaml")
    parser.add_argument(
        "--training-config", type=Path, default=ROOT / "configs/training.yaml"
    )
    parser.add_argument(
        "--policy-config", type=Path, default=ROOT / "configs/policy.yaml"
    )
    parser.add_argument("--artifacts-dir", type=Path, default=ROOT / "artifacts")
    parser.add_argument("--figure-dir", type=Path, default=ROOT / "reports/figures")
    args = parser.parse_args()
    try:
        settings = load_config(args.config)
        configure_logging(settings)
        policy_config = yaml.safe_load(args.policy_config.read_text())
        artifacts = args.artifacts_dir.resolve()
        (artifacts / "metrics").mkdir(parents=True, exist_ok=True)
        (artifacts / "predictions").mkdir(parents=True, exist_ok=True)
        model_meta = json.loads(
            (settings.paths.artifacts / "models/champion_metadata.json").read_text()
        )
        model_path = settings.paths.artifacts / "models" / model_meta["model_filename"]
        model = joblib.load(model_path)
        predictions_path = (
            settings.paths.artifacts / "predictions/validation_predictions.csv"
        )
        predictions = pd.read_csv(predictions_path)
        if model_meta["feature_order"] != list(MODEL_FEATURES):
            raise PolicyEvaluationError("feature order mismatch")
        events = _validation_events(settings, model, predictions)
        selected = select_policies(events, policy_config)
        if selected["champion"] is None:
            _write_json(
                {
                    "status": "infeasible",
                    "candidate_counts": selected["candidate_counts"],
                },
                artifacts / "metrics/validation_policy_infeasibility.json",
            )
            raise PolicyEvaluationError(
                "no nontrivial validation policy satisfies every guardrail"
            )
        methods = {
            name: serializable_result(result)
            for name, result in selected["methods"].items()
        }
        champion = selected["methods"][selected["champion"]]
        metrics_payload = {
            "status": "passed",
            "champion": selected["champion"],
            "candidate_counts": selected["candidate_counts"],
            "methods": methods,
            "replay_estimate_disclaimer": (
                "Offline upper-bound estimate assuming block_next_attempt ends the "
                "recorded sequence; not an observed causal outcome."
            ),
        }
        _write_json(
            metrics_payload, artifacts / "metrics/validation_sequential_metrics.json"
        )
        rows = []
        event_output = events.sort_values(
            ["device_id", "timestamp", "event_sequence"], kind="mergesort"
        ).reset_index(drop=True)
        for name, result in selected["methods"].items():
            if result is None:
                continue
            event_output[f"{name}_action"] = result["replay"]["action"].to_numpy()
            event_output[f"{name}_reason_code"] = result["replay"][
                "policy_reason_code"
            ].to_numpy()
            item = {
                "method": name,
                "feasible": True,
                **result["thresholds"],
                "attacker_device_block_coverage": result["metrics"][
                    "attacker_block_coverage"
                ]["rate"],
                "legitimate_device_review_or_higher_rate": result["budgets"][
                    "legitimate_review_or_higher"
                ]["rate"],
                "legitimate_device_block_rate": result["budgets"]["legitimate_block"][
                    "rate"
                ],
            }
            rows.append(item)
        event_output["authorization_position"] = champion["replay"][
            "authorization_position"
        ].to_numpy()
        event_output["champion_is_first_review"] = champion["replay"][
            "is_first_review"
        ].to_numpy()
        event_output["champion_is_first_block"] = champion["replay"][
            "is_first_block"
        ].to_numpy()
        event_output["champion_potentially_prevented"] = champion["replay"][
            "potentially_prevented"
        ].to_numpy()
        comparison = pd.DataFrame(rows).sort_values("method")
        comparison.to_csv(
            artifacts / "metrics/validation_policy_comparison.csv", index=False
        )
        event_output.to_csv(
            artifacts / "predictions/validation_sequential_events.csv", index=False
        )
        champion["device_summary"].to_csv(
            artifacts / "predictions/validation_device_summary.csv", index=False
        )
        fig_dir = args.figure_dir.resolve()
        fig_dir.mkdir(parents=True, exist_ok=True)
        fig, ax = plt.subplots(figsize=(6, 4))
        for name, result in selected["methods"].items():
            if result is None:
                continue
            within = result["metrics"]["detected_within_attempt"]
            ax.plot(
                [int(k) for k in within],
                [value["rate"] for value in within.values()],
                marker="o",
                label=name,
            )
        ax.set(
            xlabel="authorization attempt",
            ylabel="share of all attacker devices blocked",
            title="Validation detection by attempt",
        )
        ax.legend()
        fig.tight_layout()
        fig.savefig(fig_dir / "validation_detection_by_attempt.png", dpi=150)
        plt.close(fig)
        fig, ax = plt.subplots(figsize=(6, 4))
        for _, row in comparison.iterrows():
            ax.scatter(
                row["legitimate_device_block_rate"],
                row["attacker_device_block_coverage"],
                label=row["method"],
                s=70,
            )
        ax.set(
            xlabel="legitimate-device ever-blocked rate",
            ylabel="attacker-device block coverage",
            title="Validation policy tradeoff",
        )
        ax.legend()
        fig.tight_layout()
        fig.savefig(fig_dir / "validation_policy_tradeoff.png", dpi=150)
        plt.close(fig)
        hashes = {
            "model_sha256": sha256_file(model_path),
            "training_config_sha256": sha256_file(args.training_config),
            "policy_config_sha256": sha256_file(args.policy_config),
            "base_config_sha256": sha256_file(args.config),
            "validation_predictions_sha256": sha256_file(predictions_path),
        }
        frozen = {
            "policy_version": policy_config["policy_version"],
            "metric_definition_version": policy_config["metric_definition_version"],
            "action_logic_identifier": policy_config["action_logic_identifier"],
            "selected_policy_method": selected["champion"],
            "champion_thresholds": champion["thresholds"],
            "comparator_results": methods,
            "budgets": {
                key: value
                for key, value in policy_config.items()
                if "rate" in key or key == "subgroup_block_guardrails"
            },
            "model_filename": model_meta["model_filename"],
            "feature_order": list(MODEL_FEATURES),
            "feature_hash": model_meta["feature_hash"],
            "dataset_version": model_meta["dataset_version"],
            "frozen_checksums": frozen_checksums(settings),
            **hashes,
            "phase3_static_threshold": model_meta["threshold"],
            "post_authorization_semantics": (
                "attempt k is processed; action affects attempt k+1"
            ),
            "test_data_used_for_selection": False,
            "readiness_status": "ready_for_final_test",
        }
        policy_path = artifacts / "policy/frozen_policy.json"
        _write_json(frozen, policy_path)
        os.environ.setdefault("MLFLOW_ALLOW_FILE_STORE", "true")
        mlflow.set_tracking_uri(settings.paths.mlflow.resolve().as_uri())
        mlflow.set_experiment("card-testing-sentinel-policy")
        for name, result in selected["methods"].items():
            if result is None:
                continue
            with mlflow.start_run(run_name=f"validation-policy-{name}"):
                mlflow.log_params({"method": name, **result["thresholds"]})
                mlflow.log_metrics(
                    {
                        "attacker_device_block_coverage": result["metrics"][
                            "attacker_block_coverage"
                        ]["rate"],
                        "legitimate_device_block_rate": result["budgets"][
                            "legitimate_block"
                        ]["rate"],
                    }
                )
        checksum = sha256_file(policy_path)
        print(f"Frozen validation policy: method={selected['champion']}")
        print(f"Policy sha256={checksum}")
        return 0
    except (OSError, ValueError, KeyError, SentinelError) as exc:
        print(f"Policy freeze failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
