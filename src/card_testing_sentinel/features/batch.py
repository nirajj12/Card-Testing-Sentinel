"""Offline batch replay of raw lifecycle events through the live engine.

This drives the exact ``FeatureEngine`` the API uses, so batch-built training
features and online features cannot diverge. It is the only way features are
ever produced -- the dataset generator emits raw events and never computes a
feature itself.

Labels are deliberately absent here. The caller joins them afterwards on
``request_id`` / ``device_id``, so nothing label-shaped can reach the engine.
"""

from __future__ import annotations

import pandas as pd

from card_testing_sentinel.domain.events import LifecycleEvent
from card_testing_sentinel.features.engine import FeatureEngine
from card_testing_sentinel.features.specification import MODEL_FEATURES

#: Columns carried through to the feature table for joining and grouping only.
CARRIED_COLUMNS = ("request_id", "device_id", "session_id", "timestamp")

#: Read raw CSVs with these dtypes: `card_last4` is a zero-padded string and
#: must never be parsed as an integer.
RAW_DTYPES = {
    "card_last4": "string",
    "card_bin": "string",
    "merchant_id": "string",
    "customer_id": "string",
    "device_id": "string",
    "session_id": "string",
    "ip_fingerprint": "string",
}


def read_raw_events(path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=RAW_DTYPES)


def lifecycle_event(record: dict) -> LifecycleEvent:
    payload = {
        key: value
        for key, value in record.items()
        if key in LifecycleEvent.model_fields and pd.notna(value)
    }
    return LifecycleEvent.model_validate(payload)


def replay_events(events: pd.DataFrame) -> pd.DataFrame:
    """Replay one already-isolated partition and return one feature row per
    authorization request, in the contract's feature order."""
    engine = FeatureEngine()
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
                    **{name: snapshot[name] for name in MODEL_FEATURES},
                }
            )
        elif event.event_type == "authorization_outcome":
            engine.record_outcome(event)
        else:
            engine.record_checkout(event)
    return pd.DataFrame(rows, columns=[*CARRIED_COLUMNS, *MODEL_FEATURES])


def build_feature_table(raw: pd.DataFrame, labels: pd.DataFrame) -> pd.DataFrame:
    """Replay each split independently (fresh engine state per split, so no
    history bleeds across the train/validation boundary), then join labels."""
    parts = []
    for split in sorted(raw["split"].unique()):
        features = replay_events(raw.loc[raw["split"].eq(split)])
        features["split"] = split
        parts.append(features)
    table = pd.concat(parts, ignore_index=True)
    device_labels = labels[
        ["device_id", "label", "population", "scenario", "merchant_id", "merchant_kind"]
    ].drop_duplicates("device_id")
    return table.merge(
        device_labels, on="device_id", how="left", validate="many_to_one"
    )
