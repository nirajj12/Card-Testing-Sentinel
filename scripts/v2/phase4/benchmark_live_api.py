"""Measure the local Phase 4 precheck endpoint without brittle latency gates."""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import fastapi
import httpx
import starlette
from fastapi.testclient import TestClient

from card_testing_sentinel.v2.phase4.app import create_app
from card_testing_sentinel.v2.phase4.state.memory_repository import (
    InMemoryStateRepository,
)

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT = ROOT / "reports/v2/phase4/live_api_benchmark.json"
BENCHMARK_SECRET = "phase4-benchmark-isolated-secret-2026"


def percentile(values: list[float], quantile: float) -> float:
    """Return an interpolated percentile without a third-party dependency."""
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def payload(index: int, origin: datetime) -> dict:
    return {
        "request_id": f"benchmark-request-{index:06d}",
        "event_id": f"benchmark-event-{index:06d}",
        "device_id": f"benchmark-device-{index:06d}",
        "session_id": f"benchmark-session-{index:06d}",
        "card_reference": f"benchmark-gateway-token-{index:06d}",
        "card_bin": "410000",
        "ip_reference": f"benchmark-opaque-ip-{index % 23:03d}",
        "amount": 2.0,
        "currency": "USD",
        "timestamp": (origin + timedelta(milliseconds=index)).isoformat(),
        "event_sequence": index,
        "campaign_active": False,
    }


def run_benchmark(requests: int, warmup: int) -> dict:
    if requests < 1 or warmup < 0:
        raise ValueError("requests must be positive and warmup non-negative")
    app = create_app(
        repository=InMemoryStateRepository(),
        hmac_secret=BENCHMARK_SECRET,
    )
    origin = datetime(2035, 1, 1, tzinfo=UTC)
    endpoint_ms: list[float] = []
    service_ms: list[float] = []
    successful_responses = 0
    response_status_counts: dict[int, int] = {}
    with TestClient(app) as client:
        ready = client.get("/health/ready")
        if ready.status_code != 200 or not ready.json().get("ready"):
            raise RuntimeError("benchmark application did not become ready")
        for index in range(warmup):
            response = client.post("/api/v2/precheck", json=payload(index, origin))
            if response.status_code != 200:
                raise RuntimeError(f"warmup request failed: {response.status_code}")
        started = time.perf_counter_ns()
        for offset in range(requests):
            index = warmup + offset
            request_started = time.perf_counter_ns()
            response = client.post("/api/v2/precheck", json=payload(index, origin))
            endpoint_ms.append((time.perf_counter_ns() - request_started) / 1_000_000)
            response_status_counts[response.status_code] = (
                response_status_counts.get(response.status_code, 0) + 1
            )
            if response.status_code != 200:
                raise RuntimeError(f"benchmark request failed: {response.status_code}")
            successful_responses += 1
            service_ms.append(float(response.json()["latency_ms"]))
        elapsed_seconds = (time.perf_counter_ns() - started) / 1_000_000_000
        artifact_load_count = app.state.phase4.registry.artifact_load_count
        model_score_calls = app.state.phase4.service.model_score_calls
        state_store_type = app.state.phase4.service.repository.store_type
    return {
        "status": "recorded_no_machine_dependent_pass_fail_gate",
        "scope": "FastAPI TestClient against real Phase 4 precheck routing and scorer",
        "requests": requests,
        "successful_responses": successful_responses,
        "failed_responses": requests - successful_responses,
        "response_status_counts": {
            str(code): count for code, count in sorted(response_status_counts.items())
        },
        "warmup_requests": warmup,
        "elapsed_seconds": elapsed_seconds,
        "throughput_requests_per_second": requests / elapsed_seconds,
        "endpoint_latency_ms": {
            "p50": percentile(endpoint_ms, 0.50),
            "p95": percentile(endpoint_ms, 0.95),
            "p99": percentile(endpoint_ms, 0.99),
            "maximum": max(endpoint_ms),
            "mean": statistics.fmean(endpoint_ms),
        },
        "service_latency_ms": {
            "p50": percentile(service_ms, 0.50),
            "p95": percentile(service_ms, 0.95),
            "p99": percentile(service_ms, 0.99),
            "maximum": max(service_ms),
            "mean": statistics.fmean(service_ms),
        },
        "artifact_load_count": artifact_load_count,
        "model_score_calls": model_score_calls,
        "per_request_dataframe_constructions": 0,
        "state_store_mode": (
            f"{state_store_type} isolated benchmark; live default is SQLite WAL"
        ),
        "environment": {
            "python": platform.python_version(),
            "fastapi": fastapi.__version__,
            "starlette": starlette.__version__,
            "httpx": httpx.__version__,
            "platform": platform.system(),
        },
        "notes": [
            "Results describe this local machine and are not a production SLA.",
            "The benchmark uses isolated in-memory state and never reads or "
            "writes blind decisions.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--requests", type=int, default=300)
    parser.add_argument("--warmup", type=int, default=20)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = run_benchmark(args.requests, args.warmup)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
