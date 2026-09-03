"""Measure local, sequential HTTP latency for the active precheck endpoint."""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import time
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "artifacts/runtime/phase_4c_precheck_latency.json"


def percentile(values: list[float], percentile_value: float) -> float:
    """Return a linearly interpolated percentile from ordered observations."""
    if not values:
        raise ValueError("at least one latency observation is required")
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile_value / 100.0
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def summarize(values: list[float]) -> dict[str, float]:
    return {
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "p50": percentile(values, 50),
        "p90": percentile(values, 90),
        "p95": percentile(values, 95),
        "p99": percentile(values, 99),
        "min": min(values),
        "max": max(values),
        "stddev": statistics.pstdev(values),
    }


def _json_request(base_url: str, path: str, payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="GET" if data is None else "POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        if response.status != 200:
            raise RuntimeError(f"unexpected HTTP status: {response.status}")
        result = json.loads(response.read())
    if not isinstance(result, dict):
        raise RuntimeError("endpoint returned a non-object response")
    return result


def build_payload(run_id: str, index: int) -> dict:
    return {
        "request_id": f"phase4c-benchmark-{run_id}-r{index}",
        "event_id": f"phase4c-benchmark-{run_id}-q{index}",
        "merchant_id": "phase4c-benchmark-merchant",
        "customer_id": f"phase4c-benchmark-customer-{index}",
        "device_id": f"phase4c-benchmark-device-{index}",
        "session_id": f"phase4c-benchmark-session-{index}",
        "ip_reference": f"198.51.100.{index % 200 + 1}",
        "amount": 100.0,
        "currency": "INR",
        "campaign_active": False,
        "timestamp": datetime.now(UTC).isoformat(),
        "event_sequence": 1,
    }


def benchmark(base_url: str, warmup: int, measured: int) -> dict:
    system = _json_request(base_url, "/api/system")
    expected = {
        "active_runtime_version": "postblind-v3.1-prototype-runtime",
        "model_version": "model-v3.1",
        "feature_count": 44,
        "policy_version": "validation-selected-v2",
        "production_ready": False,
    }
    for field, value in expected.items():
        if system.get(field) != value:
            raise RuntimeError(f"active runtime mismatch: {field}")

    run_id = uuid.uuid4().hex[:12]
    errors = 0
    successes = 0
    latencies: list[float] = []
    for index in range(warmup + measured):
        payload = build_payload(run_id, index)
        started = time.perf_counter_ns()
        try:
            _json_request(base_url, "/api/precheck", payload)
        except (urllib.error.URLError, TimeoutError, RuntimeError):
            if index >= warmup:
                errors += 1
            continue
        elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
        if index >= warmup:
            latencies.append(elapsed_ms)
            successes += 1
    if not latencies:
        raise RuntimeError("benchmark produced no successful measured requests")

    cpu = platform.processor().strip() or platform.machine().strip() or "unavailable"
    return {
        "runtime": system["active_runtime_version"],
        "model": system["model_version"],
        "feature_count": system["feature_count"],
        "policy": system["policy_version"],
        "environment": {
            "os": platform.platform(),
            "python": platform.python_version(),
            "cpu": cpu,
            "benchmark_mode": "local_non_production",
        },
        "methodology": {
            "endpoint": "/api/precheck",
            "timing": "client_monotonic_http_round_trip",
            "execution": "sequential",
            "fixtures": "synthetic_non_pbrss_unique_devices",
        },
        "warmup_requests": warmup,
        "measured_requests": measured,
        "successes": successes,
        "errors": errors,
        "latency_ms": summarize(latencies),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--warmup", type=int, default=50)
    parser.add_argument("--measured", type=int, default=500)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if args.warmup < 0 or args.measured < 1:
        raise SystemExit("warmup must be non-negative and measured must be positive")
    result = benchmark(args.base_url, args.warmup, args.measured)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
