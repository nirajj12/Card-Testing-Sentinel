"""End-to-end binding tests for the active frozen v2 runtime."""

import asyncio
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from card_testing_sentinel.api.contracts import PrecheckRequest
from card_testing_sentinel.app import create_app
from card_testing_sentinel.features.engine_v2 import FeatureEngineV2
from card_testing_sentinel.features.specification_v2 import (
    MODEL_FEATURES_V2,
    MODEL_FEATURES_V2_SHA256,
)
from card_testing_sentinel.modeling.registry import ArtifactRegistry
from card_testing_sentinel.persistence.sqlite_repository import SQLiteStateRepository
from card_testing_sentinel.security.identifiers import IdentifierProtector
from card_testing_sentinel.services.risk_service import RiskService
from tests.helpers import precheck_payload

ROOT = Path(__file__).resolve().parents[2]
SECRET = "active-v2-test-secret-at-least-sixteen-characters"


def test_active_api_uses_the_exact_frozen_v2_stack_and_evidence(client):
    runtime = client.app.state.runtime
    system = client.get("/api/system").json()
    assert system["active_runtime_version"] == "frozen-v2-runtime"
    assert system["feature_count"] == 39
    assert system["feature_contract_sha256"] == MODEL_FEATURES_V2_SHA256
    assert system["model_version"] == "model-v2"
    assert system["policy_version"] == "validation-selected-v2"
    assert system["policy_family"] == "evidence_gated_v2"
    assert isinstance(runtime.service.engine, FeatureEngineV2)
    assert tuple(runtime.registry.model._artifact.feature_names) == MODEL_FEATURES_V2

    response = client.post("/api/precheck", json=precheck_payload()).json()
    stored = runtime.service.repository.get_request(response["request_id"])
    assert stored is not None
    assert stored.decision == response["decision"]
    assert stored.risk_score == pytest.approx(response["risk_score"])

    calls = runtime.service.model_score_calls
    evidence = client.get("/api/metrics/blind").json()
    assert evidence["blind_version"] == "blind-v2"
    assert evidence["verdict"] == "WEAK"
    assert runtime.service.model_score_calls == calls


def test_restart_recovery_reproduces_the_v2_decision(tmp_path):
    registry = ArtifactRegistry.load(ROOT)
    database = tmp_path / "live_state_v2.sqlite3"
    protector = IdentifierProtector.from_secret(SECRET)
    request = PrecheckRequest(**precheck_payload())

    first_service = RiskService(registry, SQLiteStateRepository(database), protector)
    first = asyncio.run(first_service.precheck(request))
    first_service.close()

    recovered = RiskService(registry, SQLiteStateRepository(database), protector)
    replay = asyncio.run(recovered.precheck(request))
    assert replay.idempotent_replay is True
    assert replay.decision == first.decision
    assert replay.risk_score == first.risk_score
    assert isinstance(recovered.engine, FeatureEngineV2)
    recovered.close()


def test_contract_mismatch_prevents_application_readiness(tmp_path):
    runtime = yaml.safe_load((ROOT / "configs/runtime.yaml").read_text())
    runtime["runtime"]["feature_contract_sha256"] = "0" * 64
    bad_runtime = tmp_path / "runtime.yaml"
    bad_runtime.write_text(yaml.safe_dump(runtime))

    config = yaml.safe_load((ROOT / "configs/app.yaml").read_text())
    config["runtime_manifest_path"] = str(bad_runtime)
    bad_config = tmp_path / "app.yaml"
    bad_config.write_text(yaml.safe_dump(config))

    app = create_app(root=ROOT, config_path=bad_config, hmac_secret=SECRET)
    with TestClient(app) as client:
        ready = client.get("/health/ready").json()
        assert ready["ready"] is False
        assert "does not match Feature Contract v2" in ready["error"]


def test_docker_builds_and_serves_the_react_bundle_as_non_root():
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert "FROM node:22.13.1-alpine AS frontend-build" in dockerfile
    assert "RUN npm ci" in dockerfile
    assert "RUN npm run build" in dockerfile
    assert (
        "COPY --from=frontend-build /build/frontend/dist ./frontend/dist" in dockerfile
    )
    assert "FROM python:3.11.15-slim AS runtime" in dockerfile
    assert "USER sentinel" in dockerfile
    assert 'VOLUME ["/app/data/runtime"]' in dockerfile
    assert "HEALTHCHECK" in dockerfile
