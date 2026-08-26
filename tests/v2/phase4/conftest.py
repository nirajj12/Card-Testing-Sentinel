from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from card_testing_sentinel.v2.phase4.app import create_app
from card_testing_sentinel.v2.phase4.artifact_registry import ArtifactRegistry
from card_testing_sentinel.v2.phase4.state.memory_repository import (
    InMemoryStateRepository,
)

ROOT = Path(__file__).resolve().parents[3]
SECRET = "phase4-test-secret-at-least-sixteen-characters"


@pytest.fixture(scope="session")
def registry() -> ArtifactRegistry:
    return ArtifactRegistry.load(ROOT)


@pytest.fixture()
def client(registry, monkeypatch):
    monkeypatch.setattr(
        "card_testing_sentinel.v2.phase4.app.ArtifactRegistry.load",
        lambda _root: registry,
    )
    app = create_app(
        repository=InMemoryStateRepository(),
        hmac_secret=SECRET,
    )
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def base_time() -> datetime:
    return datetime(2030, 1, 1, tzinfo=UTC)
