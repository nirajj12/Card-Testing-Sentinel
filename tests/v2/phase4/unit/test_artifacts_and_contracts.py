import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from card_testing_sentinel.v2.phase4.app import create_app
from card_testing_sentinel.v2.phase4.artifact_registry import ArtifactRegistry
from card_testing_sentinel.v2.phase4.contracts import PrecheckRequest
from card_testing_sentinel.v2.phase4.exceptions import ArtifactIntegrityError
from card_testing_sentinel.v2.phase4.state.memory_repository import (
    InMemoryStateRepository,
)

ROOT = Path(__file__).resolve().parents[4]
PROTECTED = (
    "artifacts/v2/phase2b/training/models/selected_model.joblib",
    "artifacts/v2/phase2c/confirmation/frozen_operational_policy.json",
    "artifacts/v2/phase3/blind/pre_access_freeze.json",
    "artifacts/v2/phase3/blind/final_hash_manifest.json",
)


def _copy_protected(tmp_path):
    for relative in PROTECTED:
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, destination)


@pytest.mark.parametrize("relative", PROTECTED[:2] + PROTECTED[3:])
def test_tampered_model_policy_or_manifest_refused(tmp_path, relative):
    _copy_protected(tmp_path)
    with (tmp_path / relative).open("ab") as stream:
        stream.write(b"tamper")
    with pytest.raises(ArtifactIntegrityError, match="protected artifact drift"):
        ArtifactRegistry.load(tmp_path)


def test_missing_artifact_refused(tmp_path):
    _copy_protected(tmp_path)
    (tmp_path / PROTECTED[0]).unlink()
    with pytest.raises(ArtifactIntegrityError, match="protected artifact drift"):
        ArtifactRegistry.load(tmp_path)


def test_wrong_feature_contract_refused(monkeypatch):
    monkeypatch.setattr(
        "card_testing_sentinel.v2.phase4.artifact_registry.MODEL_FEATURE_COLUMNS",
        ("wrong",),
    )
    with pytest.raises(ArtifactIntegrityError, match="feature count"):
        ArtifactRegistry.load(ROOT)


def test_correct_registry_startup(registry):
    assert registry.policy["candidate_id"] == "phase2c_002"
    assert registry.system_summary()["feature_count"] == 44
    assert registry.artifact_load_count == 1


def test_missing_hmac_secret_fails_readiness(registry, monkeypatch):
    monkeypatch.delenv("CTS_HMAC_SECRET", raising=False)
    monkeypatch.setattr(
        "card_testing_sentinel.v2.phase4.app.ArtifactRegistry.load",
        lambda _root: registry,
    )
    app = create_app(repository=InMemoryStateRepository())
    with TestClient(app) as client:
        response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json()["ready"] is False
    assert "CTS_HMAC_SECRET" in response.json()["error"]


def test_strict_contract_rejects_nonfinite_boolean_and_extra_fields(base_time):
    valid = {
        "request_id": "r",
        "event_id": "e",
        "device_id": "d",
        "session_id": "s",
        "card_reference": "c",
        "card_bin": "410000",
        "ip_reference": "198.51.100.1",
        "amount": 2.0,
        "currency": "USD",
        "timestamp": base_time,
        "event_sequence": 1,
        "campaign_active": False,
    }
    assert PrecheckRequest.model_validate(valid).amount == 2.0
    for field, value in (
        ("amount", float("inf")),
        ("amount", True),
        ("event_sequence", True),
    ):
        payload = {**valid, field: value}
        with pytest.raises(ValidationError):
            PrecheckRequest.model_validate(payload)
    with pytest.raises(ValidationError):
        PrecheckRequest.model_validate({**valid, "population": "attack"})
