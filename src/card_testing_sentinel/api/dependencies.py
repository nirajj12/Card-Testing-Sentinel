from __future__ import annotations

from dataclasses import dataclass, field
from typing import Annotated, Any

from fastapi import Depends, Request

from card_testing_sentinel.modeling.registry import ArtifactRegistry
from card_testing_sentinel.services.risk_service import RiskService


@dataclass
class ApplicationRuntime:
    config: dict
    registry: ArtifactRegistry | None = None
    service: RiskService | None = None
    demo: Any = None
    razorpay: Any = None
    ready: bool = False
    startup_error: str | None = None
    recent_api_latencies_ms: list[float] = field(default_factory=list)


def get_runtime(request: Request) -> ApplicationRuntime:
    return request.app.state.runtime


RuntimeDependency = Annotated[ApplicationRuntime, Depends(get_runtime)]
