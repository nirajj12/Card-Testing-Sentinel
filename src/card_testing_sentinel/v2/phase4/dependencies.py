"""Application runtime container and FastAPI dependency."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Annotated, Any

from fastapi import Depends, Request

from card_testing_sentinel.v2.phase4.artifact_registry import ArtifactRegistry
from card_testing_sentinel.v2.phase4.service import LiveScoringService


@dataclass
class Phase4Runtime:
    config: dict
    registry: ArtifactRegistry | None = None
    service: LiveScoringService | None = None
    demo: Any = None
    ready: bool = False
    startup_error: str | None = None
    recent_api_latencies_ms: list[float] = field(default_factory=list)


def get_runtime(request: Request) -> Phase4Runtime:
    return request.app.state.phase4


RuntimeDependency = Annotated[Phase4Runtime, Depends(get_runtime)]
