"""Training-only batch replay using the online Phase 2B engine."""

from time import perf_counter_ns

import pandas as pd

from card_testing_sentinel.v2.data.contracts import LifecycleEvent
from card_testing_sentinel.v2.phase2b.engine import Phase2BFeatureEngine
from card_testing_sentinel.v2.phase2b.features import MODEL_FEATURE_COLUMNS

METADATA_COLUMNS = (
    "event_id",
    "request_id",
    "timestamp",
    "device_id",
    "session_id",
    "label",
    "population",
    "attack_subtype",
    "scenario_tag",
)


def lifecycle_event(record: dict) -> LifecycleEvent:
    payload = {
        key: value
        for key, value in record.items()
        if key in LifecycleEvent.model_fields and pd.notna(value)
    }
    if "card_bin" in payload:
        payload["card_bin"] = str(payload["card_bin"]).removesuffix(".0")
    return LifecycleEvent.model_validate(payload)


def replay_training_events(
    events: pd.DataFrame, *, measure_latency: bool = False
) -> tuple[pd.DataFrame, list[int]]:
    """Replay a globally ordered, already-isolated training partition."""
    engine = Phase2BFeatureEngine()
    rows: list[dict] = []
    latencies_ns: list[int] = []
    ordered = events.sort_values(["timestamp", "event_sequence"], kind="mergesort")
    for record in ordered.to_dict("records"):
        event = lifecycle_event(record)
        if event.event_type == "authorization_request":
            started = perf_counter_ns()
            snapshot = engine.precheck(event)
            if measure_latency:
                latencies_ns.append(perf_counter_ns() - started)
            rows.append(
                {
                    "event_id": event.event_id,
                    "request_id": event.request_id,
                    "timestamp": event.timestamp.isoformat(),
                    "device_id": event.device_id,
                    "session_id": event.session_id,
                    **{name: snapshot[name] for name in MODEL_FEATURE_COLUMNS},
                    "label": int(record["label"]),
                    "population": record["population"],
                    "attack_subtype": record.get("attack_subtype"),
                    "scenario_tag": record["scenario_tag"],
                }
            )
        elif event.event_type == "authorization_outcome":
            engine.record_outcome(event)
        else:
            engine.record_completion(event)
    return pd.DataFrame(rows), latencies_ns
