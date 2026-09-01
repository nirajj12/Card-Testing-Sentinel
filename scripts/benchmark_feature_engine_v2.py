"""Local latency of FeatureEngine v2 feature extraction.

    python scripts/benchmark_feature_engine_v2.py [--events N]

Measures the engine only -- no model, no policy, no Razorpay call. Three
operations are timed separately:

* `snapshot`      -- building the 39-feature vector from prior state
* `model_vector`  -- ordering it into the contract's array
* `state_update`  -- committing the request and pruning

Numbers are for this machine and this Python build. They are reported, not
asserted: a benchmark that hardcodes a pass mark is not a benchmark.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

from card_testing_sentinel.features.batch import lifecycle_event, read_raw_events
from card_testing_sentinel.features.engine_v2 import FeatureEngineV2
from card_testing_sentinel.features.specification_v2 import MODEL_FEATURES_V2

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/generated/development_v3"


def percentiles(samples: list[float]) -> dict[str, float]:
    array = np.array(samples, dtype=float) * 1000.0  # milliseconds
    return {
        "count": int(array.size),
        "median_ms": round(float(np.median(array)), 4),
        "p95_ms": round(float(np.percentile(array, 95)), 4),
        "p99_ms": round(float(np.percentile(array, 99)), 4),
        "max_ms": round(float(np.max(array)), 4),
    }


def main(limit: int) -> dict:
    raw = read_raw_events(DATA / "raw_events.csv")
    raw = raw.loc[raw.split.eq("train")].sort_values(
        ["timestamp", "event_sequence"], kind="mergesort"
    )
    records = raw.head(limit).to_dict("records")

    engine = FeatureEngineV2()
    snapshot_times: list[float] = []
    vector_times: list[float] = []
    update_times: list[float] = []

    for record in records:
        event = lifecycle_event(record)
        if event.event_type == "authorization_request":
            start = time.perf_counter()
            snapshot = engine.snapshot(event)
            snapshot_times.append(time.perf_counter() - start)

            start = time.perf_counter()
            np.fromiter(
                (snapshot[name] for name in MODEL_FEATURES_V2),
                dtype=float,
                count=len(MODEL_FEATURES_V2),
            )
            vector_times.append(time.perf_counter() - start)

            start = time.perf_counter()
            engine.record_request(event)
            update_times.append(time.perf_counter() - start)
        elif event.event_type == "authorization_outcome":
            start = time.perf_counter()
            engine.record_outcome(event)
            update_times.append(time.perf_counter() - start)
        else:
            start = time.perf_counter()
            engine.record_checkout(event)
            update_times.append(time.perf_counter() - start)

    combined = [
        snapshot + vector
        for snapshot, vector in zip(snapshot_times, vector_times, strict=True)
    ]
    return {
        "events_processed": len(records),
        "feature_snapshot": percentiles(snapshot_times),
        "model_vector_construction": percentiles(vector_times),
        "state_update": percentiles(update_times),
        "snapshot_plus_vector": percentiles(combined),
        "state_size": engine.state_size(),
        "note": (
            "Local, single-process, no model and no gateway call. The "
            "snapshot is recomputed here before record_request, so the "
            "snapshot timing is measured on its own rather than inferred."
        ),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", type=int, default=40000)
    args = parser.parse_args()
    print(json.dumps(main(args.events), indent=2))
