"""Repeatable benchmarks for the real pre-authorization decision path.

This script intentionally never calls ``/api/system`` for latency samples and
never opens blind evaluation rows. It uses the non-blind golden feature fixture
for model-only timing and an isolated temporary SQLite database for HTTP-path
timing. All traffic uses unique identifiers except the separately labelled
idempotent-retry benchmark.
"""

from __future__ import annotations

import json
import logging
import statistics
import time
import warnings
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from importlib import metadata
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient
from sklearn.exceptions import InconsistentVersionWarning

from card_testing_sentinel.app import PROJECT_ROOT, create_app
from card_testing_sentinel.features.specification import MODEL_FEATURES
from card_testing_sentinel.persistence.sqlite_repository import SQLiteStateRepository
from card_testing_sentinel.policy.engine import OperationalPolicy
from card_testing_sentinel.services.scenario_generation import SCENARIO_PLANS

SECRET = "decision-benchmark-secret-at-least-sixteen-characters"
MODEL_WARMUPS = 2_000
MODEL_MEASUREMENTS = 20_000
HTTP_WARMUP_REQUESTS = 20
IDEMPOTENT_MEASUREMENTS = 500


def _stats(samples_ms: list[float]) -> dict:
    ordered = sorted(samples_ms)
    count = len(ordered)

    def percentile(fraction: float) -> float:
        return ordered[max(0, int(count * fraction) - 1)]

    total_seconds = sum(samples_ms) / 1_000
    return {
        "count": count,
        "p50_ms": statistics.median(ordered),
        "p95_ms": percentile(0.95),
        "p99_ms": percentile(0.99),
        "maximum_ms": max(ordered),
        "mean_ms": statistics.fmean(ordered),
        "throughput_per_second": count / total_seconds,
    }


def _measure(callable_) -> tuple[object, float]:
    started = time.perf_counter_ns()
    value = callable_()
    return value, (time.perf_counter_ns() - started) / 1_000_000


@dataclass
class CausalClock:
    timestamp: datetime = datetime(2035, 1, 1, tzinfo=UTC)
    sequence: int = 0

    def next(self, seconds: int = 1) -> tuple[str, int]:
        self.timestamp += timedelta(seconds=max(1, seconds))
        sequence = self.sequence
        self.sequence += 1
        return self.timestamp.isoformat(), sequence


def _submit_scenario(
    client: TestClient,
    scenario: str,
    namespace: str,
    clock: CausalClock,
    samples: list[float] | None,
) -> dict:
    saw_block = False
    later_after_block = 0
    failures = 0
    decisions: list[str] = []
    first_payload: dict | None = None

    for spec in SCENARIO_PLANS[scenario]:
        timestamp, sequence = clock.next(spec.gap_seconds)
        request_id = f"{namespace}-request-{spec.attempt}"
        payload = {
            "request_id": request_id,
            "event_id": f"{namespace}-precheck-{spec.attempt}",
            "device_id": f"{namespace}-device",
            "session_id": f"{namespace}-{spec.session_suffix}",
            "card_reference": f"{namespace}-{spec.card_suffix}",
            "card_bin": "410000",
            "ip_reference": f"{namespace}-{spec.ip_suffix}",
            "amount": spec.amount,
            "currency": "INR",
            "timestamp": timestamp,
            "event_sequence": sequence,
            "campaign_active": spec.campaign_active,
        }
        if first_payload is None:
            first_payload = payload
        response, elapsed_ms = _measure(
            lambda payload=payload: client.post("/api/precheck", json=payload)
        )
        if samples is not None:
            samples.append(elapsed_ms)
        if response.status_code != 200:
            failures += 1
            continue
        decision = response.json()["decision"]
        decisions.append(decision)
        if saw_block:
            later_after_block += 1
        saw_block = saw_block or decision == "block"

        if decision == "block":
            continue
        outcome_timestamp, outcome_sequence = clock.next()
        outcome = client.post(
            "/api/outcomes",
            json={
                "event_id": f"{namespace}-outcome-{spec.attempt}",
                "request_id": request_id,
                "device_id": f"{namespace}-device",
                "session_id": f"{namespace}-{spec.session_suffix}",
                "timestamp": outcome_timestamp,
                "event_sequence": outcome_sequence,
                "authorization_result": spec.authorization_result,
                "decline_reason": spec.decline_reason,
            },
        )
        failures += int(outcome.status_code != 200)
        if spec.authorization_result == "approved":
            checkout_timestamp, checkout_sequence = clock.next(30)
            checkout = client.post(
                "/api/checkouts",
                json={
                    "event_id": f"{namespace}-checkout-{spec.attempt}",
                    "request_id": request_id,
                    "device_id": f"{namespace}-device",
                    "session_id": f"{namespace}-{spec.session_suffix}",
                    "timestamp": checkout_timestamp,
                    "event_sequence": checkout_sequence,
                },
            )
            failures += int(checkout.status_code != 200)

    return {
        "failures": failures,
        "decisions": decisions,
        "saw_block": saw_block,
        "later_attempts_after_block": later_after_block,
        "first_payload": first_payload,
    }


def _model_only(runtime) -> dict:
    fixture = json.loads(
        (PROJECT_ROOT / "tests/fixtures/golden/live_parity.json").read_text()
    )
    values = np.asarray(fixture["attempts"][0]["features"], dtype=float)
    snapshot = dict(zip(MODEL_FEATURES, values, strict=True))
    scorer = runtime.registry.scorer

    prepared = np.where(np.isnan(values), scorer.imputer, values)
    normalized = (prepared - scorer.mean) / scorer.scale

    def raw_model():
        linear = np.dot(normalized, scorer.coefficients) + scorer.intercept
        return float(1.0 / (1.0 + np.exp(-linear)))

    raw_score = raw_model()

    def calibration():
        return float(np.interp(raw_score, scorer.isotonic_x, scorer.isotonic_y))

    risk_score = calibration()
    for _ in range(MODEL_WARMUPS):
        scorer.score_array(values)

    raw_samples: list[float] = []
    calibration_samples: list[float] = []
    for _ in range(MODEL_MEASUREMENTS):
        _, elapsed = _measure(raw_model)
        raw_samples.append(elapsed)
        _, elapsed = _measure(calibration)
        calibration_samples.append(elapsed)

    policy = OperationalPolicy(runtime.registry.policy)
    policy_samples: list[float] = []
    for index in range(MODEL_MEASUREMENTS):
        _, elapsed = _measure(
            lambda index=index: policy.decide(
                device_id=f"policy-benchmark-device-{index}",
                event_id=f"policy-benchmark-event-{index}",
                timestamp=datetime(2035, 1, 1, tzinfo=UTC),
                session_id="policy-benchmark-session",
                risk_score=risk_score,
                snapshot=snapshot,
            )
        )
        policy_samples.append(elapsed)

    combined_policy = OperationalPolicy(runtime.registry.policy)
    combined_samples: list[float] = []
    for index in range(MODEL_MEASUREMENTS):

        def combined(index=index):
            _, calibrated = scorer.score_array(values)
            return combined_policy.decide(
                device_id=f"combined-benchmark-device-{index}",
                event_id=f"combined-benchmark-event-{index}",
                timestamp=datetime(2035, 1, 1, tzinfo=UTC),
                session_id="combined-benchmark-session",
                risk_score=calibrated,
                snapshot=snapshot,
            )

        _, elapsed = _measure(combined)
        combined_samples.append(elapsed)

    return {
        "prepared_feature_count": len(values),
        "warmup_count": MODEL_WARMUPS,
        "measured_count_per_component": MODEL_MEASUREMENTS,
        "failures": 0,
        "raw_model": _stats(raw_samples),
        "isotonic_calibration": _stats(calibration_samples),
        "policy_decision": _stats(policy_samples),
        "combined_model_calibration_policy": _stats(combined_samples),
    }


def _traffic_benchmark(client: TestClient, clock: CausalClock) -> dict:
    for index in range(HTTP_WARMUP_REQUESTS // 2):
        _submit_scenario(client, "normal_customer", f"warmup-{index}", clock, None)

    profiles = {
        "normal_customer": [("normal_customer", index) for index in range(125)],
        "burst_attack": [("burst_attacker", index) for index in range(40)],
        "mixed": [
            (scenario, index)
            for index in range(25)
            for scenario in ("normal_customer", "burst_attacker")
        ],
    }
    results = {}
    first_payload = None
    for profile, scenarios in profiles.items():
        samples: list[float] = []
        failures = 0
        blocks = 0
        later_after_block = 0
        for scenario, index in scenarios:
            run = _submit_scenario(
                client,
                scenario,
                f"{profile}-{index}-{scenario}",
                clock,
                samples,
            )
            first_payload = first_payload or run["first_payload"]
            failures += run["failures"]
            blocks += int(run["saw_block"])
            later_after_block += run["later_attempts_after_block"]
        results[profile] = {
            **_stats(samples),
            "failures": failures,
            "scenario_runs": len(scenarios),
            "runs_reaching_block": blocks,
            "later_attempts_after_block": later_after_block,
        }
    return {"profiles": results, "first_payload": first_payload}


def _idempotent_benchmark(client: TestClient, payload: dict) -> dict:
    original = client.post("/api/precheck", json=payload)
    if original.status_code != 200:
        raise RuntimeError("idempotency benchmark setup request failed")
    original_body = original.json()
    samples: list[float] = []
    failures = 0
    preserved = True
    for _ in range(IDEMPOTENT_MEASUREMENTS):
        response, elapsed = _measure(lambda: client.post("/api/precheck", json=payload))
        samples.append(elapsed)
        failures += int(response.status_code != 200)
        if response.status_code == 200:
            body = response.json()
            preserved &= body["idempotent_replay"] is True
            preserved &= body["decision"] == original_body["decision"]
            preserved &= (
                body["device_state_version"] == original_body["device_state_version"]
            )
    return {
        **_stats(samples),
        "failures": failures,
        "original_decision_and_state_preserved": preserved,
        "model_rescore_count": 0,
    }


def main() -> None:
    warnings.simplefilter("error", InconsistentVersionWarning)
    with TemporaryDirectory(prefix="cts-decision-benchmark-") as temporary:
        db_path = Path(temporary) / "benchmark.sqlite3"
        repository = SQLiteStateRepository(db_path)
        application = create_app(repository=repository, hmac_secret=SECRET)
        cold_started = time.perf_counter_ns()
        with TestClient(application) as client:
            ready = client.get("/health/ready")
            cold_start_ms = (time.perf_counter_ns() - cold_started) / 1_000_000
            ready.raise_for_status()
            logging.getLogger("card_testing_sentinel.application").setLevel(
                logging.WARNING
            )

            runtime = application.state.runtime
            if runtime.registry.blind_row_load_count != 0:
                raise RuntimeError("benchmark must not load frozen blind rows")

            dataframe_constructions = 0
            original_dataframe = pd.DataFrame

            def counted_dataframe(*args, **kwargs):
                nonlocal dataframe_constructions
                dataframe_constructions += 1
                return original_dataframe(*args, **kwargs)

            pd.DataFrame = counted_dataframe
            try:
                model_only = _model_only(runtime)
                traffic = _traffic_benchmark(client, CausalClock())
                retry_payload = dict(traffic.pop("first_payload"))
                retry_payload["request_id"] = "idempotency-benchmark-request"
                retry_payload["event_id"] = "idempotency-benchmark-event"
                retry_payload["device_id"] = "idempotency-benchmark-device"
                retry_payload["session_id"] = "idempotency-benchmark-session"
                retry_payload["card_reference"] = "idempotency-benchmark-card"
                retry_payload["ip_reference"] = "idempotency-benchmark-network"
                latest = repository.latest_order()
                retry_payload["timestamp"] = (
                    datetime.fromisoformat(latest[0]) + timedelta(seconds=1)
                ).isoformat()
                retry_payload["event_sequence"] = latest[1] + 1
                score_calls_before = runtime.service.model_score_calls
                idempotent = _idempotent_benchmark(client, retry_payload)
                idempotent["model_rescore_count"] = (
                    runtime.service.model_score_calls - score_calls_before - 1
                )
            finally:
                pd.DataFrame = original_dataframe

            database = repository.status()
            result = {
                "benchmark": "real-preauthorization-decision-path",
                "timestamp": datetime.now(UTC).isoformat(),
                "python": metadata.version("pip")
                and __import__("sys").version.split()[0],
                "versions": {
                    name: metadata.version(name)
                    for name in (
                        "fastapi",
                        "starlette",
                        "uvicorn",
                        "h11",
                        "pydantic",
                        "numpy",
                        "scipy",
                        "scikit-learn",
                        "joblib",
                    )
                },
                "cold_start_ms": cold_start_ms,
                "model_only": model_only,
                "end_to_end": {
                    "measurement_boundary": (
                        "in-process ASGI HTTP POST /api/precheck including validation, "
                        "HMAC, state, causal features, model, calibration, policy, "
                        "SQLite persistence, middleware, serialization and response"
                    ),
                    "warmup_requests": HTTP_WARMUP_REQUESTS,
                    **traffic,
                },
                "idempotent_retry": idempotent,
                "artifact_load_count": runtime.registry.artifact_load_count,
                "blind_row_load_count": runtime.registry.blind_row_load_count,
                "per_request_dataframe_construction_count": dataframe_constructions,
                "sqlite": database,
            }
            if result["artifact_load_count"] != 1:
                raise RuntimeError("protected artifacts must load exactly once")
            if result["blind_row_load_count"] != 0:
                raise RuntimeError("benchmark loaded frozen blind rows")
            if dataframe_constructions != 0:
                raise RuntimeError("decision path constructed a pandas DataFrame")
            if database["journal_mode"] != "wal" or database["integrity"] != "ok":
                raise RuntimeError("temporary SQLite database failed WAL/quick_check")
            print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
