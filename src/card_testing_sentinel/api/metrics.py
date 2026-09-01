import json

from fastapi import APIRouter

from card_testing_sentinel.common.paths import project_root

router = APIRouter(prefix="/api/metrics")

_UNAVAILABLE = {
    "status": "unavailable",
    "reason": "Dataset V2 model and blind evaluation have not been generated yet.",
}


@router.get("/blind")
def blind_metrics() -> dict:
    path = project_root() / "artifacts/evaluation/blind_metrics_v1_1.json"
    if not path.is_file():
        return dict(_UNAVAILABLE)
    result = json.loads(path.read_text())
    policy = result["policy_metrics"]["blind"]
    scenarios = result["scenario_metrics"]
    detection = result["detection_delay"]["attack_detected_by_attempt"]
    return {
        "status": "available",
        "source": "artifacts/evaluation/blind_metrics_v1_1.json",
        "label": "Held-out synthetic evaluation",
        "blind_version": result["blind_version"],
        "active_device_counts": {
            "attack": policy["attack_devices"],
            "legitimate": policy["legitimate_devices"],
        },
        "headline": {
            "attack_intervention_rate": policy["attack_review_or_higher_recall"],
            "attack_block_rate": policy["attack_block_recall"],
            "legitimate_intervention_rate": policy["legitimate_review_or_higher_rate"],
            "legitimate_block_rate": policy["legitimate_block_rate"],
        },
        "detection_by_attempt": detection,
        "scenario_metrics": [
            {
                "scenario": row["scenario"],
                "population": row["population"],
                "devices": row["devices"],
                "intervention_rate": row["review_or_higher_rate"],
                "block_rate": row["block_rate"],
            }
            for row in scenarios
        ],
        "limitations": {
            "hardest_attacks": ["ultra_patient_tester", "cross_device_campaign"],
            "highest_friction": ["persistent_genuine_failures"],
        },
        "disclosure": (
            "Synthetic benchmark results on devices that produced at least one "
            "authorization request. They are not production performance claims."
        ),
    }
