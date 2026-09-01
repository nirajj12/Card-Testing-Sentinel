"""Application factory for the local fraud-operations console."""

from __future__ import annotations

import os
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from card_testing_sentinel.api import (
    demo,
    health,
    live,
    metrics,
    razorpay,
    replay,
    webhooks,
)
from card_testing_sentinel.api.dependencies import ApplicationRuntime
from card_testing_sentinel.common.config import load_config
from card_testing_sentinel.common.environment import load_local_environment
from card_testing_sentinel.common.logging import configure_logging
from card_testing_sentinel.common.paths import project_root
from card_testing_sentinel.domain.events import EventContractError
from card_testing_sentinel.domain.exceptions import ApplicationError
from card_testing_sentinel.modeling.registry import ArtifactRegistry
from card_testing_sentinel.persistence.repository import StateRepository
from card_testing_sentinel.persistence.sqlite_repository import SQLiteStateRepository
from card_testing_sentinel.security.identifiers import IdentifierProtector
from card_testing_sentinel.services.demo import DemoManager
from card_testing_sentinel.services.razorpay import (
    RazorpayCheckoutService,
    RazorpayClient,
    RazorpayCredentials,
)
from card_testing_sentinel.services.risk_service import RiskService

PROJECT_ROOT = project_root()


def create_app(
    *,
    root: Path = PROJECT_ROOT,
    config_path: Path | None = None,
    repository: StateRepository | None = None,
    hmac_secret: str | None = None,
) -> FastAPI:
    load_local_environment(
        root,
        (
            "CTS_HMAC_SECRET",
            "RAZORPAY_KEY_ID",
            "RAZORPAY_KEY_SECRET",
            "RAZORPAY_WEBHOOK_SECRET",
        ),
    )
    config = load_config(config_path or root / "configs/app.yaml")
    configure_logging(str(config.get("log_level", "INFO")))
    templates = Jinja2Templates(
        directory=root / "src/card_testing_sentinel/web/templates"
    )
    frontend_dist = root / "frontend/dist"

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        runtime = ApplicationRuntime(config=config)
        application.state.runtime = runtime
        try:
            registry = ArtifactRegistry.load(
                root, manifest_path=root / config["runtime_manifest_path"]
            )
            protector = IdentifierProtector.from_secret(
                hmac_secret or os.environ.get("CTS_HMAC_SECRET")
            )
            state_repository = repository or SQLiteStateRepository(
                root / config["database_path"]
            )
            service = RiskService(registry, state_repository, protector)
            credentials = RazorpayCredentials.from_environment()
            runtime.razorpay = RazorpayCheckoutService(
                client=(RazorpayClient(credentials) if credentials else None),
                repository=state_repository,
                risk_service=service,
                protector=protector,
                webhook_secret=os.environ.get("RAZORPAY_WEBHOOK_SECRET"),
            )
            runtime.registry = registry
            runtime.service = service
            if bool(config.get("demo_mode")):
                runtime.demo = DemoManager(service, protector)
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
        title="PreAuth Sentinel",
        version=str(config["version"]),
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
    )
    application.state.runtime = ApplicationRuntime(config=config)
    application.mount(
        "/static",
        StaticFiles(directory=root / "src/card_testing_sentinel/web/static"),
        name="static",
    )
    if frontend_dist.is_dir():
        application.mount(
            "/assets",
            StaticFiles(directory=frontend_dist / "assets"),
            name="frontend-assets",
        )
    application.include_router(health.router)
    application.include_router(live.router)
    application.include_router(metrics.router)
    application.include_router(razorpay.router)
    application.include_router(webhooks.router)
    application.include_router(replay.router)
    application.include_router(demo.router)

    @application.middleware("http")
    async def request_context(request: Request, call_next):
        started = time.perf_counter_ns()
        correlation_id = request.headers.get("X-Correlation-ID") or uuid.uuid4().hex
        request.state.correlation_id = correlation_id
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = correlation_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' https://checkout.razorpay.com "
            "https://cdn.razorpay.com; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; "
            "connect-src 'self' https://api.razorpay.com; "
            "frame-src https://api.razorpay.com https://checkout.razorpay.com; "
            "frame-ancestors 'none'"
        )
        runtime = request.app.state.runtime
        runtime.recent_api_latencies_ms.append(
            (time.perf_counter_ns() - started) / 1_000_000
        )
        runtime.recent_api_latencies_ms = runtime.recent_api_latencies_ms[-1000:]
        return response

    @application.exception_handler(ApplicationError)
    async def application_error(request: Request, error: ApplicationError):
        return JSONResponse(
            status_code=error.status_code,
            content={
                "error": error.error_code,
                "message": str(error),
                "correlation_id": getattr(request.state, "correlation_id", None),
            },
        )

    @application.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError):
        fields = sorted(
            {
                ".".join(str(part) for part in item.get("loc", ())[1:])
                for item in error.errors()
                if item.get("loc")
            }
        )
        return JSONResponse(
            status_code=422,
            content={
                "error": "invalid_request",
                "message": "request failed strict schema validation",
                "fields": [name for name in fields if name],
                "correlation_id": getattr(request.state, "correlation_id", None),
            },
        )

    @application.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException):
        return JSONResponse(
            status_code=error.status_code,
            content={
                "error": "not_found" if error.status_code == 404 else "http_error",
                "message": str(error.detail),
                "correlation_id": getattr(request.state, "correlation_id", None),
            },
        )

    @application.exception_handler(EventContractError)
    async def lifecycle_error(request: Request, error: EventContractError):
        return JSONResponse(
            status_code=409,
            content={
                "error": "invalid_lifecycle_transition",
                "message": str(error),
                "correlation_id": getattr(request.state, "correlation_id", None),
            },
        )

    async def product_page(request: Request):
        if (frontend_dist / "index.html").is_file():
            return FileResponse(frontend_dist / "index.html")
        return templates.TemplateResponse(
            request=request,
            name="dashboard.html",
            context={
                "app_name": config["app_name"],
                "demo_mode": bool(config.get("demo_mode")),
            },
        )

    application.add_api_route("/", product_page, methods=["GET"])
    for product_path in ("/store", "/checkout", "/how-it-works", "/evidence"):
        application.add_api_route(product_path, product_page, methods=["GET"])

    return application


app = create_app()
