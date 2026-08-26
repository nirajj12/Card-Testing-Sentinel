"""Integration coverage for the fail-closed startup compatibility path.

Simulates a runtime that failed to start because the installed toolchain
does not match the frozen model's serialization environment, and asserts
the failure is visible end-to-end: readiness, /api/system, and demo
endpoints all report the real problem instead of a masking 404/422.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from card_testing_sentinel.app import create_app
from card_testing_sentinel.modeling.compatibility import (
    CompatibilityReport,
    RuntimeCompatibilityError,
)
from card_testing_sentinel.persistence.memory_repository import (
    InMemoryStateRepository,
)

SECRET = "application-test-secret-at-least-sixteen-characters"

INCOMPATIBLE_REPORT = CompatibilityReport(
    compatible=False,
    expected={"python": "3.11", "scikit_learn": "1.6.1", "numpy": "1.26.4"},
    actual={"python": "3.11", "scikit_learn": "1.9.0", "numpy": "1.26.4"},
    mismatches=[{"package": "scikit_learn", "expected": "1.6.1", "actual": "1.9.0"}],
)


@pytest.fixture()
def incompatible_client(monkeypatch):
    def _raise(_root: Path):
        raise RuntimeCompatibilityError(
            "runtime is incompatible with the frozen model's serialization "
            "environment: scikit_learn expected 1.6.1, found 1.9.0",
            INCOMPATIBLE_REPORT,
        )

    monkeypatch.setattr(
        "card_testing_sentinel.app.ArtifactRegistry.load",
        staticmethod(_raise),
    )
    app = create_app(repository=InMemoryStateRepository(), hmac_secret=SECRET)
    with TestClient(app) as test_client:
        yield test_client


def test_health_ready_is_false_with_clear_error_on_incompatible_runtime(
    incompatible_client,
):
    response = incompatible_client.get("/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is False
    assert body["status"] == "not_ready"
    assert "scikit_learn" in body["error"]
    assert "1.6.1" in body["error"]
    assert "1.9.0" in body["error"]


def test_api_system_explains_expected_and_actual_versions(incompatible_client):
    response = incompatible_client.get("/api/system")
    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is False
    assert body["compatibility"]["compatible"] is False
    assert body["compatibility"]["expected"]["scikit_learn"] == "1.6.1"
    assert body["compatibility"]["actual"]["scikit_learn"] == "1.9.0"
    assert body["compatibility"]["mismatches"][0]["package"] == "scikit_learn"


@pytest.mark.parametrize(
    ("method", "path", "json_body"),
    [
        ("GET", "/api/demo/scenarios", None),
        ("POST", "/api/demo/start", {"scenario": "normal_customer"}),
        ("POST", "/api/demo/step", {"demo_id": "demo_doesnotexist"}),
        ("POST", "/api/demo/reset", None),
    ],
)
def test_demo_unavailable_because_startup_failed_is_not_masked_as_404_or_422(
    incompatible_client, method, path, json_body
):
    """Every demo control must fail closed with the real startup problem
    (503) rather than a generic "demo disabled" 404, and must never let a
    client reach a secondary 422 from an empty scenario list."""
    response = incompatible_client.request(method, path, json=json_body)
    assert response.status_code == 503
    assert "scikit_learn" in response.json()["message"]


def test_demo_disabled_by_config_still_returns_404_when_runtime_is_ready(
    client,
):
    """Once the runtime is actually ready, turning demo mode off in config
    is still a plain 404 -- the 503 path above is specific to startup
    failure, not a blanket replacement for the config-driven 404."""
    assert client.app.state.runtime.ready is True
    client.app.state.runtime.demo = None

    response = client.get("/api/demo/scenarios")

    assert response.status_code == 404
    assert response.json()["message"] == "demo mode is disabled"
