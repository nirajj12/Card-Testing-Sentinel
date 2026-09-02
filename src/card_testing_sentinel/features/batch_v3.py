"""Offline batch replay through FeatureEngine v3.

Drives FeatureEngineV3 in deterministic global event sequence order to ensure
batch training features and online runtime feature computation never diverge.
"""

from __future__ import annotations

import pandas as pd

from card_testing_sentinel.features.batch import RAW_DTYPES, lifecycle_event
from card_testing_sentinel.features.engine_v3 import FeatureEngineV3
from card_testing_sentinel.features.specification_v3 import MODEL_FEATURES_V3

CARRIED_COLUMNS = ("request_id", "device_id", "session_id", "timestamp")

__all__ = [
    "CARRIED_COLUMNS",
    "RAW_DTYPES",
    "build_feature_table_v3",
    "replay_events_v3",
]


def replay_events_v3(
    events: pd.DataFrame, *, engine: FeatureEngineV3 | None = None
) -> pd.DataFrame:
    """Replay one partition in global event order."""
    engine = engine or FeatureEngineV3()
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
                    **{name: snapshot[name] for name in MODEL_FEATURES_V3},
                }
            )
        elif event.event_type == "authorization_outcome":
            engine.record_outcome(event)
        else:
            engine.record_checkout(event)
    return pd.DataFrame(rows, columns=[*CARRIED_COLUMNS, *MODEL_FEATURES_V3])


def build_feature_table_v3(raw: pd.DataFrame, labels: pd.DataFrame) -> pd.DataFrame:
    """Replay each split with a fresh engine, then join labels."""
    parts = []
    for split in sorted(raw["split"].unique()):
        features = replay_events_v3(raw.loc[raw["split"].eq(split)])
        features["split"] = split
        parts.append(features)
    table = pd.concat(parts, ignore_index=True)
    columns = [
        "device_id",
        "actor_id",
        "leakage_group_id",
        "customer_id",
        "label",
        "population",
        "scenario",
        "merchant_id",
        "merchant_kind",
        "counterfactual_pair_id",
        "counterfactual_role",
    ]
    device_labels = labels[
        [name for name in columns if name in labels.columns]
    ].drop_duplicates("device_id")
    return table.merge(
        device_labels, on="device_id", how="left", validate="many_to_one"
    )
