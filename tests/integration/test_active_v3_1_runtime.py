"""Binding, parity, integrity, and recovery tests for active Model v3.1."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest
import yaml

from card_testing_sentinel.api.contracts import (
    CheckoutRequest,
    OutcomeRequest,
    PrecheckRequest,
)
from card_testing_sentinel.features.batch_v3 import replay_events_v3
from card_testing_sentinel.features.engine_v3 import FeatureEngineV3
from card_testing_sentinel.features.specification_v3 import (
    MODEL_FEATURES_V3,
    MODEL_FEATURES_V3_SHA256,
)
from card_testing_sentinel.modeling.registry import (
    ArtifactRegistry,
    RuntimeManifestError,
)
from card_testing_sentinel.persistence.sqlite_repository import SQLiteStateRepository
from card_testing_sentinel.security.identifiers import IdentifierProtector
from card_testing_sentinel.services.risk_service import RiskService
from tests.helpers import precheck_payload

ROOT = Path(__file__).resolve().parents[2]
SECRET = "active-v3-test-secret-at-least-sixteen-characters"


def test_active_api_binds_the_exact_frozen_v3_1_stack(client):
    app_config = yaml.safe_load((ROOT / "configs/app.yaml").read_text())
    assert app_config["runtime_manifest_path"] == "configs/runtime_v3_1.yaml"
    assert app_config["database_path"] == "data/runtime/live_state_v3_1.sqlite3"
    runtime = client.app.state.runtime
    system = client.get("/api/system").json()
    assert system["active_runtime_version"] == "postblind-v3.1-prototype-runtime"
    assert system["runtime_stage"] == "evaluated_prototype_candidate"
    assert system["production_ready"] is False
    assert system["model_version"] == "model-v3.1"
    assert system["model_family"] == "hist_gradient_boosting"
    assert system["model_candidate"] == "hist_gb_2"
    assert system["calibration"] == "sigmoid"
    assert system["feature_contract_version"] == "merchant-visible-causal-3.1"
    assert system["feature_contract_sha256"] == MODEL_FEATURES_V3_SHA256
    assert system["feature_count"] == 44
    assert system["policy_version"] == "validation-selected-v2"
    assert system["evaluation_version"] == "pbrss-v1"
    assert system["evaluation_consumed"] is True
    assert system["evaluation_conclusion"] == "MIXED"
    assert isinstance(runtime.service.engine, FeatureEngineV3)
    assert tuple(runtime.registry.model._artifact.feature_names) == MODEL_FEATURES_V3


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("model_artifact_sha256", "0" * 64),
        ("feature_contract_artifact_sha256", "1" * 64),
        ("model_metadata_sha256", "2" * 64),
        ("policy_artifact_sha256", "3" * 64),
        ("evaluation_result_manifest_sha256", "4" * 64),
        ("evaluation_freeze_manifest_sha256", "5" * 64),
    ],
)
def test_v3_1_registry_fails_closed_on_frozen_hash_drift(tmp_path, field, value):
    manifest = yaml.safe_load((ROOT / "configs/runtime_v3_1.yaml").read_text())
    manifest["runtime"][field] = value
    path = tmp_path / "runtime_v3_1.yaml"
    path.write_text(yaml.safe_dump(manifest))
    with pytest.raises(RuntimeManifestError, match="hash does not match"):
        ArtifactRegistry.load(ROOT, manifest_path=path)


def _events() -> list[dict]:
    start = datetime(2032, 1, 1, tzinfo=UTC)
    return [
        {
            "event_id": "q1",
            "request_id": "r1",
            "event_sequence": 1,
            "timestamp": start,
            "event_type": "authorization_request",
            "merchant_id": "m1",
            "customer_id": "c1",
            "device_id": "d1",
            "session_id": "s1",
            "ip_fingerprint": "ip1",
            "amount": 2.0,
            "currency": "INR",
            "campaign_active": False,
        },
        {
            "event_id": "o1",
            "request_id": "r1",
            "event_sequence": 2,
            "timestamp": start + timedelta(seconds=1),
            "event_type": "authorization_outcome",
            "device_id": "d1",
            "session_id": "s1",
            "authorization_result": "declined",
            "failure_reason": "generic_decline",
            "payment_method": "card",
            "card_last4": "1111",
            "card_network": "visa",
        },
        {
            "event_id": "q2",
            "request_id": "r2",
            "event_sequence": 3,
            "timestamp": start + timedelta(seconds=7),
            "event_type": "authorization_request",
            "merchant_id": "m1",
            "customer_id": "c1",
            "device_id": "d1",
            "session_id": "s2",
            "ip_fingerprint": "ip2",
            "amount": 3.0,
            "currency": "INR",
            "campaign_active": False,
        },
    ]


def test_offline_and_online_v3_1_feature_vectors_are_exactly_equal():
    events = _events()
    offline = replay_events_v3(pd.DataFrame(events))
    online_engine = FeatureEngineV3()
    online_rows = []
    from card_testing_sentinel.domain.events import LifecycleEvent

    for payload in events:
        event = LifecycleEvent.model_validate(payload)
        if event.event_type == "authorization_request":
            snapshot = online_engine.record_request(event)
            online_rows.append([snapshot[name] for name in MODEL_FEATURES_V3])
        else:
            online_engine.record_outcome(event)
    assert list(offline.columns[4:]) == list(MODEL_FEATURES_V3)
    assert offline.loc[:, list(MODEL_FEATURES_V3)].values.tolist() == online_rows


def test_registry_score_matches_frozen_v3_1_artifact_for_same_ordered_vector(registry):
    event = _events()[0]
    from card_testing_sentinel.domain.events import LifecycleEvent

    snapshot = FeatureEngineV3().snapshot(LifecycleEvent.model_validate(event))
    ordered = [snapshot[name] for name in MODEL_FEATURES_V3]
    expected_frame = pd.DataFrame([ordered], columns=MODEL_FEATURES_V3)
    artifact = registry.model._artifact
    expected = artifact.score_frame(expected_frame)[0]
    with patch.object(artifact, "score_frame", wraps=artifact.score_frame) as native:
        actual = registry.model.score(snapshot)
    supplied_frame = native.call_args.args[0]
    pd.testing.assert_frame_equal(supplied_frame, expected_frame, check_exact=True)
    assert actual == pytest.approx(expected, rel=0.0, abs=0.0)


def test_pbrss_endpoint_only_displays_frozen_evidence(client):
    service = client.app.state.runtime.service
    calls_before = service.model_score_calls
    response = client.get("/api/metrics/blind")
    assert response.status_code == 200
    body = response.json()
    assert body["verdict"] == "MIXED"
    assert body["policy_metrics"]["legitimate_review_or_higher_rate"] == 0.2072
    assert body["policy_metrics"]["legitimate_block_rate"] == 0.0016
    assert service.model_score_calls == calls_before

    source = (ROOT / "src/card_testing_sentinel/api/metrics.py").read_text()
    for forbidden in (
        ".score(",
        "score_frame(",
        "predict(",
        "predict_proba(",
        "evaluate_pbrss",
        "generate_post_blind_stress",
    ):
        assert forbidden not in source


def test_v3_1_restart_replays_full_lifecycle_and_continues(tmp_path):
    registry = ArtifactRegistry.load(
        ROOT, manifest_path=ROOT / "configs/runtime_v3_1.yaml"
    )
    database = tmp_path / "live_state_v3_1.sqlite3"
    protector = IdentifierProtector.from_secret(SECRET)
    base = datetime(2033, 1, 1, tzinfo=UTC)
    request = PrecheckRequest(**precheck_payload(base=base, amount=100.0))

    first = RiskService(registry, SQLiteStateRepository(database), protector)
    decision = asyncio.run(first.precheck(request))
    assert decision.decision == "allow"
    asyncio.run(
        first.outcome(
            OutcomeRequest(
                event_id="outcome-1",
                request_id=request.request_id,
                device_id=request.device_id,
                session_id=request.session_id,
                timestamp=base + timedelta(seconds=11),
                event_sequence=4,
                authorization_result="approved",
            )
        )
    )
    asyncio.run(
        first.checkout(
            CheckoutRequest(
                event_id="checkout-1",
                request_id=request.request_id,
                device_id=request.device_id,
                session_id=request.session_id,
                timestamp=base + timedelta(seconds=12),
                event_sequence=5,
            )
        )
    )
    first.close()

    recovered = RiskService(registry, SQLiteStateRepository(database), protector)
    replay = asyncio.run(recovered.precheck(request))
    assert replay.idempotent_replay is True
    assert replay.decision == decision.decision
    assert isinstance(recovered.engine, FeatureEngineV3)
    later = PrecheckRequest(**precheck_payload(index=2, base=base, amount=100.0))
    continued = asyncio.run(recovered.precheck(later))
    assert continued.device_state_version == 4
    recovered.close()
