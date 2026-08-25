import json

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from card_testing_sentinel.api.app import (
    ArtifactRegistry,
    EvaluationRequest,
    create_app,
)
from card_testing_sentinel.features.spec import MODEL_FEATURES


class FakeRegistry:
    ready = True
    config = {
        "protected_hashes": {"model": "a" * 64, "policy": "b" * 64},
        "app_name": "Card-Testing Sentinel",
        "app_version": "0.5.0",
    }
    policy = {
        "selected_policy_method": "rules_only",
        "dataset_version": "v4",
        "action_logic_identifier": "post-v1",
        "feature_hash": "c" * 64,
    }
    metrics = {"status": "complete"}
    devices = pd.DataFrame(
        [
            {
                "device_id": "safe-device",
                "population": "flash_sale",
                "attack_subtype": None,
                "scenario_exposures": "flash_hard_retry",
                "authorization_count": 4,
                "first_block_position": 3,
                "ever_blocked": True,
                "attempts_processed_through_detection": 3,
                "distinct_cards_before_detection_attempt": 1,
                "distinct_cards_processed_through_detection": 2,
                "seconds_to_detection": 2.5,
                "remaining_recorded_attempts_after_detection": 1,
            }
        ]
    )
    events = pd.DataFrame(
        [
            {
                "device_id": "safe-device",
                "authorization_position": 1,
                "timestamp": "2026-01-01T00:00:00Z",
                "card_token": "must-not-leak",
                "risk_score": 0.2,
                "rule_score": 0,
                "fixed_rule_reason_codes": None,
                "rules_only_action": "allow",
                "ml_only_action": "allow",
                "combined_action": "allow",
                "champion_is_first_block": False,
                "champion_potentially_prevented": False,
            }
        ]
    )

    def evaluate(self, request):
        return {
            "selected_policy_method": "rules_only",
            "features": len(request.features),
        }


def test_health_contract_and_dashboard():
    with TestClient(create_app(registry=FakeRegistry())) as client:
        assert client.get("/health/live").status_code == 200
        assert client.get("/health/ready").json()["champion_method"] == "rules_only"
        assert client.get("/api/v1/system").json()["hgb_role"] == "advisory risk scorer"
        assert "Limits are part of the result" in client.get("/").text
        assert client.get("/static/dashboard.css").status_code == 200


def test_device_catalogue_filters_scenario_without_raw_fields():
    with TestClient(create_app(registry=FakeRegistry())) as client:
        response = client.get(
            "/api/v1/devices", params={"scenario_exposure": "flash_hard_retry"}
        )
        assert response.status_code == 200
        assert response.json()["items"] == [
            {
                "device_id": "safe-device",
                "population": "flash_sale",
                "attack_subtype": None,
                "scenario_exposures": "flash_hard_retry",
                "authorization_count": 4,
                "first_block_position": 3,
                "ever_blocked": True,
            }
        ]


def test_exact_feature_contract_and_safe_timeline_projection():
    valid = {name: 0.0 for name in MODEL_FEATURES}
    with TestClient(create_app(registry=FakeRegistry())) as client:
        assert (
            client.post("/api/v1/evaluate", json={"features": valid}).status_code == 200
        )
        invalid = dict(valid)
        invalid["unexpected"] = 1.0
        assert (
            client.post("/api/v1/evaluate", json={"features": invalid}).status_code
            == 422
        )
        response = client.get("/api/v1/devices/safe-device/timeline")
        assert response.status_code == 200
        assert "must-not-leak" not in response.text
        assert "card_token" not in response.text

    invalid = dict(valid)
    invalid[MODEL_FEATURES[0]] = float("inf")
    with pytest.raises(ValidationError):
        EvaluationRequest(features=invalid)


def test_artifact_registry_rejects_missing_or_mismatched_files(tmp_path):
    config = tmp_path / "app.yaml"
    config.write_text(
        "protected_hashes:\n"
        + "\n".join(
            f"  {name}: {json.dumps('0' * 64)}"
            for name in [
                "model",
                "policy",
                "final_metrics",
                "final_events",
                "final_devices",
            ]
        )
    )
    with pytest.raises(RuntimeError, match="artifact_verification_failed:model"):
        ArtifactRegistry(root=tmp_path, config_path=config)
