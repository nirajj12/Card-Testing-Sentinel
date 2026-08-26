import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from card_testing_sentinel.features.specification import MODEL_FEATURES

ROOT = Path(__file__).resolve().parents[2]


class CapturingScorer:
    def __init__(self, scorer):
        self.scorer = scorer
        self.rows = []

    def score_snapshot(self, snapshot):
        raw_score, risk_score = self.scorer.score_snapshot(snapshot)
        self.rows.append(
            {
                "features": [float(snapshot[name]) for name in MODEL_FEATURES],
                "raw_model_score": raw_score,
                "risk_score": risk_score,
            }
        )
        return raw_score, risk_score


def test_non_blind_golden_runtime_parity(client):
    fixture = json.loads((ROOT / "tests/fixtures/golden/live_parity.json").read_text())
    assert fixture["source"].endswith("contains no blind rows")
    assert fixture["feature_order"] == list(MODEL_FEATURES)
    service = client.app.state.runtime.service
    original_scorer = service.registry.scorer
    capturing = CapturingScorer(original_scorer)
    service.registry.scorer = capturing
    tolerance = fixture["numerical_tolerance"]
    try:
        for expected in fixture["attempts"]:
            response = client.post("/api/precheck", json=expected["request"])
            assert response.status_code == 200
            actual = response.json()
            for key in (
                "request_id",
                "event_id",
                "decision",
                "rule_score",
                "reason_codes",
                "device_state_version",
                "idempotent_replay",
            ):
                assert actual[key] == expected["response"][key]
            assert actual["risk_score"] == pytest.approx(
                expected["response"]["risk_score"], abs=tolerance
            )
            if actual["decision"] != "block":
                outcome_index = (
                    len(
                        [
                            row
                            for row in fixture["attempts"]
                            if row["request"]["event_sequence"]
                            <= expected["request"]["event_sequence"]
                            and row["response"]["decision"] != "block"
                        ]
                    )
                    - 1
                )
                outcome_request = {
                    "event_id": f"golden-outcome-{outcome_index + 1}",
                    "request_id": expected["request"]["request_id"],
                    "device_id": expected["request"]["device_id"],
                    "session_id": expected["request"]["session_id"],
                    "timestamp": expected["request"]["timestamp"],
                    "event_sequence": expected["request"]["event_sequence"] + 1,
                    "authorization_result": "declined",
                    "decline_reason": "generic_decline",
                }
                outcome_request["timestamp"] = (
                    datetime.fromisoformat(expected["request"]["timestamp"])
                    + timedelta(seconds=1)
                ).isoformat()
                transition = client.post("/api/outcomes", json=outcome_request)
                assert transition.status_code == 200

        for actual, expected in zip(capturing.rows, fixture["attempts"], strict=True):
            assert actual["features"] == pytest.approx(
                expected["features"], abs=tolerance
            )
            assert actual["raw_model_score"] == pytest.approx(
                expected["raw_model_score"], abs=tolerance
            )
            assert actual["risk_score"] == pytest.approx(
                expected["risk_score"], abs=tolerance
            )

        retry = client.post("/api/precheck", json=fixture["attempts"][0]["request"])
        assert retry.status_code == fixture["idempotent_retry"]["status"]
        assert retry.json()["idempotent_replay"] is True
        conflict = client.post(
            "/api/precheck",
            json={**fixture["attempts"][0]["request"], "amount": 3.0},
        )
        assert conflict.status_code == fixture["conflicting_retry"]["status"]
        late = client.post(
            "/api/precheck",
            json={
                **fixture["attempts"][0]["request"],
                "request_id": "golden-late-request",
                "event_id": "golden-late-precheck",
            },
        )
        assert late.status_code == fixture["late_request"]["status"]
        assert service.model_score_calls == fixture["model_score_calls"]
    finally:
        service.registry.scorer = original_scorer
