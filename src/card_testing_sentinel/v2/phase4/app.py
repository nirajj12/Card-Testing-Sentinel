"""FastAPI application factory for the Phase 4 local fraud console."""

from __future__ import annotations

import os
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import yaml
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from card_testing_sentinel.v2.data.contracts import EventContractError, LateEventError
from card_testing_sentinel.v2.phase4.api import demo, health, live, metrics, replay
from card_testing_sentinel.v2.phase4.artifact_registry import ArtifactRegistry
from card_testing_sentinel.v2.phase4.demo import DemoManager
from card_testing_sentinel.v2.phase4.dependencies import Phase4Runtime
from card_testing_sentinel.v2.phase4.exceptions import Phase4Error
from card_testing_sentinel.v2.phase4.logging import configure_phase4_logging
from card_testing_sentinel.v2.phase4.security import IdentifierProtector
from card_testing_sentinel.v2.phase4.service import LiveScoringService
from card_testing_sentinel.v2.phase4.state.repository import StateRepository
from card_testing_sentinel.v2.phase4.state.sqlite_repository import (
    SQLiteStateRepository,
)

ROOT = Path(__file__).resolve().parents[4]
DEFAULT_CONFIG = ROOT / "configs/v2/phase4/app.yaml"


def create_app(
    *,
    root: Path = ROOT,
    config_path: Path | None = None,
    repository: StateRepository | None = None,
    hmac_secret: str | None = None,
) -> FastAPI:
    config_file = config_path or root / "configs/v2/phase4/app.yaml"
    config = yaml.safe_load(config_file.read_text())
    configure_phase4_logging(str(config.get("log_level", "INFO")))
    templates = Jinja2Templates(
        directory=root / "src/card_testing_sentinel/v2/phase4/templates"
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        runtime = Phase4Runtime(config=config)
        application.state.phase4 = runtime
        try:
            registry = ArtifactRegistry.load(root)
            secret = hmac_secret or os.environ.get("CTS_HMAC_SECRET")
            protector = IdentifierProtector.from_secret(secret)
            state_repository = repository or SQLiteStateRepository(
                root / config["database_path"]
            )
            service = LiveScoringService(registry, state_repository, protector)
            runtime.registry = registry
            runtime.service = service
            if bool(config.get("demo_mode")):
                runtime.demo = DemoManager(registry, protector)
            runtime.ready = True
        except Exception as error:
            runtime.ready = False
            runtime.startup_error = f"{type(error).__name__}: {error}"
        yield
        if runtime.demo is not None:
            runtime.demo.reset()
        if runtime.service is not None:
            runtime.service.close()
        runtime.ready = False

    application = FastAPI(
        title="Card-Testing Sentinel V2",
        version=str(config["version"]),
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
    )
    application.state.phase4 = Phase4Runtime(config=config)
    application.mount(
        "/static/v2/phase4",
        StaticFiles(directory=root / "src/card_testing_sentinel/v2/phase4/static"),
        name="phase4-static",
    )
    application.include_router(health.router)
    application.include_router(live.router)
    application.include_router(metrics.router)
    application.include_router(replay.router)
    application.include_router(demo.router)

    @application.middleware("http")
    async def request_context(request: Request, call_next):
        started = time.perf_counter_ns()
        correlation_id = request.headers.get("X-Correlation-ID") or uuid.uuid4().hex
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = correlation_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        runtime = request.app.state.phase4
        runtime.recent_api_latencies_ms.append(
            (time.perf_counter_ns() - started) / 1_000_000
        )
        runtime.recent_api_latencies_ms = runtime.recent_api_latencies_ms[-1000:]
        return response

    @application.exception_handler(Phase4Error)
    async def phase4_error(request: Request, error: Phase4Error):
        return JSONResponse(
            status_code=error.status_code,
            content={
                "error": error.error_code,
                "message": str(error),
                "correlation_id": request.headers.get("X-Correlation-ID"),
            },
        )

    @application.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, _error: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={
                "error": "invalid_request",
                "message": "request failed strict schema validation",
            },
        )

    @application.exception_handler(EventContractError)
    async def lifecycle_error(_request: Request, error: EventContractError):
        return JSONResponse(
            status_code=409,
            content={"error": "invalid_lifecycle_transition", "message": str(error)},
        )

    @application.exception_handler(LateEventError)
    async def late_event(_request: Request, _error: LateEventError):
        return JSONResponse(
            status_code=409,
            content={
                "error": "causal_ordering_error",
                "message": "event is older than committed causal state",
            },
        )

    @application.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="dashboard.html",
            context={
                "app_name": config["app_name"],
                "demo_mode": bool(config.get("demo_mode")),
            },
        )

    return application


app = create_app()
