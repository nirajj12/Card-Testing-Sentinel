"""Offline batch replay through FeatureEngine v2.

This drives the exact engine a v2 runtime would use, so batch-built training
features and online features cannot diverge.

Ordering matters more in v2 than it did in v1. Customer state spans devices,
so a partition can no longer be replayed per device: every event that can
touch the same customer must be fed in one global ``(timestamp,
event_sequence)`` order. That ordering is the determinism contract, and
``replay_events_v2`` sorts on it explicitly rather than trusting row order.

Labels are deliberately absent. The caller joins them afterwards, so nothing
label-shaped can reach the engine.
"""

from __future__ import annotations

import pandas as pd

from card_testing_sentinel.features.batch import RAW_DTYPES, lifecycle_event
from card_testing_sentinel.features.engine_v2 import FeatureEngineV2
from card_testing_sentinel.features.specification_v2 import MODEL_FEATURES_V2

#: Carried through for joining and grouping only -- never model inputs.
CARRIED_COLUMNS = ("request_id", "device_id", "session_id", "timestamp")

__all__ = [
    "CARRIED_COLUMNS",
    "RAW_DTYPES",
    "build_feature_table_v2",
    "replay_events_v2",
]


def replay_events_v2(
    events: pd.DataFrame, *, engine: FeatureEngineV2 | None = None
) -> pd.DataFrame:
    """Replay one partition in global event order.

    Returns one row per authorization request, in the contract's order.
    """
    engine = engine or FeatureEngineV2()
    rows: list[dict] = []
    ordered = events.sort_values(["timestamp", "event_sequence"], kind="mergesort")
    for record in ordered.to_dict("records"):
        event = lifecycle_event(record)
        if event.event_type == "authorization_request":
            snapshot = engine.record_request(event)
            rows.append(
                {
                    "request_id": event.request_id,
                    "device_id": event.device_id,
                    "session_id": event.session_id,
                    "timestamp": event.timestamp.isoformat(),
                    **{name: snapshot[name] for name in MODEL_FEATURES_V2},
                }
            )
        elif event.event_type == "authorization_outcome":
            engine.record_outcome(event)
        else:
            engine.record_checkout(event)
    return pd.DataFrame(rows, columns=[*CARRIED_COLUMNS, *MODEL_FEATURES_V2])


def build_feature_table_v2(raw: pd.DataFrame, labels: pd.DataFrame) -> pd.DataFrame:
    """Replay each split with a fresh engine, then join labels.

    A fresh engine per split is what keeps train history out of validation:
    the splits share no device, customer or IP, but a single engine would
    still carry a customer's tenure across the boundary.
    """
    parts = []
    for split in sorted(raw["split"].unique()):
        features = replay_events_v2(raw.loc[raw["split"].eq(split)])
        features["split"] = split
        parts.append(features)
    table = pd.concat(parts, ignore_index=True)
    columns = [
        "device_id",
        "customer_id",
        "label",
        "population",
        "scenario",
        "merchant_id",
        "merchant_kind",
    ]
    device_labels = labels[
        [name for name in columns if name in labels.columns]
    ].drop_duplicates("device_id")
    return table.merge(
        device_labels, on="device_id", how="left", validate="many_to_one"
    )
