from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from card_testing_sentinel.app import create_app
from card_testing_sentinel.modeling.registry import ArtifactRegistry
from card_testing_sentinel.persistence.memory_repository import (
    InMemoryStateRepository,
)

ROOT = Path(__file__).resolve().parents[1]
SECRET = "application-test-secret-at-least-sixteen-characters"
PROTECTED_BLIND_ROW_FILES = {
    "blind_device_summary.csv",
    "blind_event_decisions.csv",
}


@pytest.fixture(autouse=True)
def forbid_protected_blind_row_reads(monkeypatch):
    """Fail the suite if a test semantically opens protected blind rows."""
    original_read_csv = pd.read_csv

    def guarded_read_csv(path, *args, **kwargs):
        if Path(path).name in PROTECTED_BLIND_ROW_FILES:
            raise AssertionError("protected blind rows must not be read by tests")
        return original_read_csv(path, *args, **kwargs)

    monkeypatch.setattr(pd, "read_csv", guarded_read_csv)


@pytest.fixture(scope="session")
def registry() -> ArtifactRegistry:
    return ArtifactRegistry.load(ROOT)


@pytest.fixture()
def client(registry, monkeypatch):
    monkeypatch.setattr(
        "card_testing_sentinel.app.ArtifactRegistry.load",
        lambda _root, **_kwargs: registry,
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
