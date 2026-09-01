"""One-time blind v1.1 evaluation of the frozen model and frozen policy.

    python pipelines/evaluate_blind.py

Verifies every frozen hash, spends the benchmark (consumption is recorded
before the first score), scores the frozen feature table with the frozen
model, replays the frozen policy, and writes `blind_metrics_v1_1.json`.

Nothing here fits, recalibrates or selects a threshold. Refuses to run twice.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import yaml

from card_testing_sentinel.features.specification import (
    MODEL_FEATURES,
    MODEL_FEATURES_SHA256,
)
from card_testing_sentinel.ml.blind_evaluation import (
    campaign_comparison,
    evidence_gate_analysis,
    friction_analysis,
    frozen_policy,
    load_frozen_model,
    mark_evaluation_complete,
    mark_evaluation_started,
    merchant_category,
    merchant_category_view,
    miss_analysis,
    sha256_file,
    verify_frozen_inputs,
)
from card_testing_sentinel.ml.evaluation import baseline_comparison, rule_scores
from card_testing_sentinel.ml.metrics import (
    device_weights,
    probability_metrics,
    reliability_bins,
)
from card_testing_sentinel.ml.policy_search import (
    device_view,
    merchant_view,
    replay,
    scenario_view,
    summarise,
)

ROOT = Path(__file__).resolve().parents[1]
BLIND = ROOT / "data/generated/blind"
OUT = ROOT / "artifacts/evaluation"
FREEZE = OUT / "blind_freeze_manifest.json"
BLIND_VERSION = "v1.1"
STAMP = BLIND_VERSION.replace(".", "_")


def load_blind() -> pd.DataFrame:
    """The frozen feature table, with the merchant-visible campaign flag the
    policy is told about. Feature values are read, never rebuilt."""
    features = pd.read_csv(BLIND / "features.csv")
    raw = pd.read_csv(BLIND / "raw_events.csv", dtype={"card_last4": "string"})
    requests = raw.loc[
        raw.event_type.eq("authorization_request"), ["request_id", "campaign_active"]
    ]
    merged = features.merge(
        requests, on="request_id", how="left", validate="one_to_one"
    )
    merged["campaign_active"] = (
        merged.campaign_active.astype("boolean").fillna(False).astype(bool)
    )
    return merged.sort_values("timestamp", kind="mergesort").reset_index(drop=True)


if __name__ == "__main__":
    freeze = json.loads(FREEZE.read_text())

    # 1. every frozen dependency, re-checked before anything is loaded
    verified = verify_frozen_inputs(ROOT, freeze)
    policy_artifact = json.loads(
        (ROOT / "artifacts/policy/operational_policy.json").read_text()
    )

    frame = load_blind()
    if sha256_file(BLIND / "features.csv") != freeze["dataset"]["features_sha256"]:
        raise SystemExit("blind features changed since the freeze")

    # 2. consumption is recorded BEFORE the first score exists
    started = mark_evaluation_started(FREEZE, BLIND_VERSION)

    # 3. the exact frozen model, hash-checked
    artifact = load_frozen_model(
        ROOT / "artifacts/model/risk_model.joblib",
        freeze["development"]["model_sha256"],
    )
    if tuple(artifact.feature_names) != MODEL_FEATURES:
        raise SystemExit("frozen model feature order does not match the contract")
    risk = artifact.score_frame(frame.loc[:, list(MODEL_FEATURES)])

    scores = frame[
        [
            "request_id",
            "device_id",
            "timestamp",
            "label",
            "population",
            "scenario",
            "merchant_id",
            "merchant_kind",
            "campaign_active",
        ]
    ].copy()
    scores["risk_score"] = risk
    scores.to_csv(OUT / f"blind_scores_{STAMP}.csv", index=False, lineterminator="\n")

    # 4. the exact frozen policy
    policy = frozen_policy(policy_artifact)
    replayed = replay(frame, risk, policy)
    devices = device_view(replayed)

    # 5. pre-registered metrics
    weights = device_weights(frame)
    model_metrics = probability_metrics(frame.label.to_numpy(dtype=int), risk, weights)
    policy_metrics = summarise(devices)

    scenarios = scenario_view(devices)
    scenarios["requests"] = frame.groupby("scenario").size()
    merchants = merchant_view(devices)
    merchants["requests"] = (
        frame.groupby("merchant_kind")
        .size()
        .reindex(merchants.merchant_kind)
        .to_numpy()
    )
    merchants["category"] = merchants.merchant_kind.map(merchant_category)

    rules = rule_scores(frame)
    config = yaml.safe_load((ROOT / "configs/training.yaml").read_text())["evaluation"]
    baselines = baseline_comparison(frame, risk, rules, config)
    baselines.to_csv(OUT / f"blind_baselines_{STAMP}.csv", index=False)
    scenarios.to_csv(OUT / f"blind_scenario_metrics_{STAMP}.csv")
    merchants.to_csv(OUT / f"blind_merchant_metrics_{STAMP}.csv", index=False)

    # 6. validation counterparts, read from the frozen development artifacts
    development = json.loads((OUT / "development_metrics.json").read_text())
    validation_policy = json.loads((OUT / "policy_validation_metrics.json").read_text())
    validation_baselines = pd.read_csv(OUT / "baseline_comparison.csv")

    def delta(blind_value, validation_value):
        if blind_value is None or validation_value is None:
            return None
        return round(float(blind_value) - float(validation_value), 4)

    blind_manifest = json.loads((BLIND / "manifest.json").read_text())
    device_labels = pd.read_csv(BLIND / "labels.csv").drop_duplicates("device_id")

    result = {
        "blind_version": BLIND_VERSION,
        "evaluation": {
            "started_utc": started,
            "completed_utc": datetime.now(UTC).isoformat(),
            "evaluator": "pipelines/evaluate_blind.py",
            "one_time": True,
            "refit_performed": False,
            "recalibration_performed": False,
            "threshold_selection_performed": False,
        },
        "hashes": {
            "model_sha256": freeze["development"]["model_sha256"],
            "model_metadata_sha256": freeze["development"]["model_metadata_sha256"],
            "feature_contract_sha256": freeze["development"]["feature_contract_sha256"],
            "feature_contract_code_sha256": MODEL_FEATURES_SHA256,
            "policy_sha256": freeze["development"]["policy_sha256"],
            "training_config_sha256": freeze["development"]["training_config_sha256"],
            "policy_config_sha256": freeze["development"]["policy_config_sha256"],
            "blind_spec_sha256": freeze["blind"]["blind_spec_sha256"],
            "blind_config_sha256": freeze["blind"]["blind_config_sha256"],
            "blind_generator_sha256": freeze["blind"]["blind_generator_sha256"],
            "raw_events_sha256": freeze["dataset"]["raw_events_sha256"],
            "labels_sha256": freeze["dataset"]["labels_sha256"],
            "features_sha256": freeze["dataset"]["features_sha256"],
            "manifest_sha256": freeze["dataset"]["manifest_sha256"],
            "verified_at_evaluation": verified,
        },
        "policy_applied": {
            key: getattr(policy, key)
            for key in (
                "family",
                "review_threshold",
                "block_threshold",
                "block_evidence",
                "campaign_review_increment",
                "campaign_block_increment",
            )
        }
        | {"block_ttl_seconds": int(policy.block_ttl.total_seconds())},
        "prevalence": {
            "blind_attack_device_fraction": blind_manifest[
                "realized_attack_device_fraction"
            ],
            "blind_attack_request_fraction": blind_manifest[
                "realized_attack_request_fraction"
            ],
            "blind_devices": int(blind_manifest["devices"]),
            "blind_requests": int(blind_manifest["requests"]),
            "blind_events": int(blind_manifest["events"]),
            "validation_attack_device_fraction": round(
                float(
                    validation_policy["aggregate"]["attack_devices"]
                    / (
                        validation_policy["aggregate"]["attack_devices"]
                        + validation_policy["aggregate"]["legitimate_devices"]
                    )
                ),
                4,
            ),
            "validation_attack_request_fraction": round(
                float(development["model_scores"]["positive_rate"]), 4
            ),
            "note": (
                "Benchmark prevalence differs between validation and blind. "
                "PR-AUC is prevalence-dependent, so it is reported as "
                "benchmark PR-AUC and must not be read as a production "
                "precision estimate. Recall, FPR and the per-scenario rates "
                "carry the argument."
            ),
        },
        "model_metrics": {
            "blind": {k: round(float(v), 4) for k, v in model_metrics.items()},
            "validation": {
                k: round(float(v), 4) for k, v in development["model_scores"].items()
            },
            "delta": {
                key: delta(model_metrics[key], development["model_scores"][key])
                for key in ("pr_auc", "roc_auc", "brier", "log_loss", "ece")
            },
            "note": "device-weighted, same implementations as Phase 4",
        },
        "calibration": {
            "blind_bins": reliability_bins(
                frame.label.to_numpy(dtype=int), risk, weights
            ),
            "validation_bins": development["calibration_bins"],
        },
        "policy_metrics": {
            "blind": policy_metrics,
            "validation": validation_policy["aggregate"],
            "delta": {
                key: delta(
                    policy_metrics.get(key), validation_policy["aggregate"].get(key)
                )
                for key in (
                    "attack_review_or_higher_recall",
                    "attack_block_recall",
                    "legitimate_review_or_higher_rate",
                    "legitimate_block_rate",
                    "median_first_review_attempt",
                    "p90_first_review_attempt",
                    "median_first_block_attempt",
                    "p90_first_block_attempt",
                )
            },
        },
        "detection_delay": {
            "attack_detected_by_attempt": {
                str(n): round(
                    float(
                        (devices.loc[devices.label.eq(1)].first_review_attempt <= n)
                        .fillna(False)
                        .mean()
                    ),
                    4,
                )
                for n in (1, 2, 3, 5)
            },
            "note": (
                "First-attempt detection is structurally weak by design: a "
                "first request is scored from prior attempts only, so a brand "
                "new device carries almost no evidence either way."
            ),
        },
        "scenario_metrics": json.loads(
            scenarios.reset_index().to_json(orient="records")
        ),
        "validation_scenario_metrics": {
            "attack": policy_artifact["attack_scenario_detection"],
            "legitimate": policy_artifact["legitimate_scenario_friction"],
            "note": (
                "Development family names differ from blind family names by "
                "design, so these are read side by side rather than paired."
            ),
        },
        "validation_merchant_metrics": policy_artifact["merchant_friction"],
        "merchant_metrics": json.loads(merchants.to_json(orient="records")),
        "merchant_category_metrics": merchant_category_view(devices),
        "campaign_metrics": campaign_comparison(replayed),
        "validation_campaign_metrics": validation_policy.get("campaign_comparison"),
        "evidence_gate": evidence_gate_analysis(frame, replayed, policy),
        "baselines": {
            "blind": json.loads(baselines.to_json(orient="records")),
            "validation": json.loads(validation_baselines.to_json(orient="records")),
            "note": (
                "Exactly the thresholds declared in configs/training.yaml and "
                "used on validation. No blind-optimal threshold was searched."
            ),
        },
        "miss_analysis": miss_analysis(frame, risk, devices),
        "friction_analysis": friction_analysis(frame, risk, devices, replayed),
        "shift_characterisation": (
            "Blind v1.1 is a temporally held-out, composition-shifted, "
            "new-merchant synthetic benchmark with MODEST marginal "
            "feature-distribution shift (max PSI 0.115, 27/28 features below "
            "0.10, median KS 0.032, minimum overlap 0.913). It is not a heavy "
            "covariate shift and must not be described as one."
        ),
        "device_counts": {
            "attack": int(device_labels.label.eq(1).sum()),
            "legitimate": int(device_labels.label.eq(0).sum()),
        },
    }

    OUT.mkdir(parents=True, exist_ok=True)
    metrics_path = OUT / f"blind_metrics_{STAMP}.json"
    if metrics_path.exists():
        raise SystemExit(f"{metrics_path.name} already exists; it is immutable")
    metrics_path.write_text(
        json.dumps(result, indent=2, sort_keys=True, default=str) + "\n"
    )
    mark_evaluation_complete(FREEZE, metrics_path)

    print(
        json.dumps(
            {
                "blind_version": BLIND_VERSION,
                "model_metrics": result["model_metrics"],
                "policy_metrics": result["policy_metrics"],
                "prevalence": result["prevalence"],
            },
            indent=2,
            default=str,
        )
    )
