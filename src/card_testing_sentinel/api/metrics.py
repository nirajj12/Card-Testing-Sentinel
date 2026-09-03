"""Read-only views over committed evaluation evidence."""

import csv
import json

from fastapi import APIRouter

from card_testing_sentinel.api.dependencies import RuntimeDependency

router = APIRouter(prefix="/api/metrics")


@router.get("/blind")
def blind_metrics(runtime: RuntimeDependency) -> dict:
    if runtime.registry is None:
        return {"status": "unavailable", "reason": "runtime is not ready"}
    root = runtime.registry.root
    selected = runtime.registry.runtime
    path = root / selected["evaluation_metrics_path"]
    if not path.is_file():
        return {"status": "unavailable", "reason": "evaluation metrics are missing"}

    result = json.loads(path.read_text())
    if selected["evaluation_version"] == "pbrss-v1":
        family_path = root / selected["evaluation_family_metrics_path"]
        with family_path.open(newline="") as source_file:
            rows = list(csv.DictReader(source_file))
        freeze = json.loads(
            (root / selected["evaluation_freeze_manifest_path"]).read_text()
        )
        scenario_counts = freeze["counts"]["scenarios"]
        scenario_metrics = [
            {
                "scenario": row["scenario"],
                "population": "attack" if row["label"] == "1" else "legitimate",
                "devices": int(scenario_counts[row["scenario"]]),
                "intervention_rate": float(row["reviewed"]),
                "block_rate": float(row["blocked"]),
            }
            for row in rows
        ]
        policy = result["policy"]
        delay = json.loads((root / selected["evaluation_detection_path"]).read_text())
        return {
            "status": "available",
            "source": selected["evaluation_metrics_path"],
            "label": "Frozen PBRSS-v1 evaluation",
            "blind_version": "pbrss-v1",
            "active_runtime_version": selected["version"],
            "model_version": selected["model_version"],
            "policy_version": runtime.registry.policy_version,
            "verdict": "MIXED",
            "consumed": True,
            "active_device_counts": {
                "attack": int(freeze["counts"]["attack_devices"]),
                "legitimate": int(freeze["counts"]["legitimate_devices"]),
            },
            "model_metrics": {
                name: result[name] for name in ("pr_auc", "roc_auc", "brier", "ece")
            },
            "policy_metrics": {
                name: policy[name]
                for name in (
                    "attack_review_or_higher_rate",
                    "attack_block_rate",
                    "legitimate_review_or_higher_rate",
                    "legitimate_block_rate",
                )
            },
            "headline": {
                "attack_intervention_rate": policy["attack_review_or_higher_rate"],
                "attack_block_rate": policy["attack_block_rate"],
                "legitimate_intervention_rate": policy[
                    "legitimate_review_or_higher_rate"
                ],
                "legitimate_block_rate": policy["legitimate_block_rate"],
            },
            "operating_targets": {
                "pbrss_result": "MIXED",
                "legitimate_friction": "FAIL",
            },
            "detection_by_attempt": {
                str(key): value for key, value in delay.items() if str(key).isdigit()
            },
            "scenario_metrics": scenario_metrics,
            "limitations": {
                "hardest_attacks": ["mixed_card_probe"],
                "highest_friction": ["ordinary_checkout"],
                "summary": "PBRSS RESULT REMAINS MIXED.",
            },
            "historical_evidence": {
                "version": "Blind v2",
                "source": "artifacts/evaluation/blind_v2_metrics.json",
                "comparable_to_blind_v2": False,
            },
            "replay": {
                "status": "not_packaged",
                "reason": "This endpoint reads frozen PBRSS aggregates only.",
                "missing_artifact": None,
            },
            "disclosure": (
                "Synthetic benchmark evidence only. It does not establish "
                "production fraud detection or customer performance."
            ),
        }
    delay = json.loads((root / selected["evaluation_detection_path"]).read_text())
    family_path = root / selected["evaluation_family_metrics_path"]
    with family_path.open(newline="") as source_file:
        families = list(csv.DictReader(source_file))
    scenario_metrics = [
        {
            "scenario": row["scenario"],
            "population": row["population"],
            "devices": int(row["devices"]),
            "intervention_rate": float(row["review_or_higher_rate"]),
            "block_rate": float(row["block_rate"]),
        }
        for row in families
    ]
    policy = result["policy"]
    return {
        "status": "available",
        "source": selected["evaluation_metrics_path"],
        "label": "Final frozen Blind v2 evaluation",
        "blind_version": selected["evaluation_version"],
        "active_runtime_version": selected["version"],
        "model_version": result["model_version"],
        "policy_version": runtime.registry.policy_version,
        "verdict": result["verdict"],
        "consumed": True,
        "active_device_counts": {
            "attack": policy["attack_devices"],
            "legitimate": policy["legitimate_devices"],
        },
        "model_metrics": result["model_metrics"],
        "policy_metrics": {
            "attack_review_or_higher_rate": policy["attack_review_or_higher_rate"],
            "attack_block_rate": policy["attack_block_rate"],
            "legitimate_review_or_higher_rate": policy[
                "legitimate_review_or_higher_rate"
            ],
            "legitimate_block_rate": policy["legitimate_block_rate"],
        },
        "headline": {
            "attack_intervention_rate": policy["attack_review_or_higher_rate"],
            "attack_block_rate": policy["attack_block_rate"],
            "legitimate_intervention_rate": policy["legitimate_review_or_higher_rate"],
            "legitimate_block_rate": policy["legitimate_block_rate"],
        },
        "operating_targets": result["operating_targets"],
        "detection_by_attempt": {
            attempt: values["review_or_higher_rate"]
            for attempt, values in delay["all_attacks"]["cumulative"].items()
        },
        "scenario_metrics": scenario_metrics,
        "limitations": {
            "hardest_attacks": [
                "cross_device_weak_guest",
                "cross_device_partial",
                "ultra_patient_v2",
            ],
            "highest_friction": [
                "subscription_dunning_v2",
                "persistent_card_problem_v2",
                "network_retry_storm_v2",
            ],
            "summary": result["remaining_weaknesses"],
        },
        "historical_evidence": {
            "version": "Blind v1.1",
            "source": "artifacts/evaluation/blind_metrics_v1_1.json",
            "comparable_to_blind_v2": False,
        },
        "replay": {
            "status": "not_packaged",
            "reason": (
                "Blind v2 raw event timelines are intentionally not committed; "
                "this endpoint serves frozen aggregate evidence only."
            ),
            "missing_artifact": "data/generated/blind_v2/raw_events.csv",
        },
        "disclosure": (
            "Synthetic benchmark evidence only. It does not establish production "
            "fraud detection or legitimate-customer performance."
        ),
    }
