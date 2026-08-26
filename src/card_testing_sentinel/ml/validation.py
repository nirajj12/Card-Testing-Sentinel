"""Validation for generated lifecycle and causal-feature datasets."""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd

from card_testing_sentinel.domain.events import LifecycleEvent
from card_testing_sentinel.features.batch import replay_training_events
from card_testing_sentinel.features.specification import MODEL_FEATURES


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_dataset(data_dir: Path, tolerance: float = 5e-7) -> dict:
    raw_path = data_dir / "raw_events.csv"
    split_path = data_dir / "device_splits.csv"
    feature_path = data_dir / "events_with_features.csv"
    raw = pd.read_csv(raw_path)
    devices = pd.read_csv(split_path)
    features = pd.read_csv(feature_path) if feature_path.exists() else None

    if devices.device_id.duplicated().any():
        raise ValueError("device split contract contains duplicates")
    if set(devices.split) != {"train", "validation"}:
        raise ValueError("device split contract requires train and validation")
    split_map = devices.set_index("device_id")["split"]
    if raw.device_id.map(split_map).isna().any():
        raise ValueError("every lifecycle event must map to one device split")
    if raw.event_id.duplicated().any():
        raise ValueError("event identifiers must be unique")

    contract_fields = set(LifecycleEvent.model_fields)
    for record in raw.to_dict("records"):
        payload = {
            key: value
            for key, value in record.items()
            if key in contract_fields and pd.notna(value)
        }
        if "card_bin" in payload:
            payload["card_bin"] = str(payload["card_bin"]).removesuffix(".0")
        LifecycleEvent.model_validate(payload)

    rebuilt_parts = []
    for split, events in raw.assign(split=raw.device_id.map(split_map)).groupby(
        "split", sort=True
    ):
        rebuilt, _latencies = replay_training_events(events.drop(columns="split"))
        rebuilt["split"] = split
        rebuilt_parts.append(rebuilt)
    rebuilt = pd.concat(rebuilt_parts, ignore_index=True).sort_values("event_id")
    if not np.isfinite(rebuilt.loc[:, MODEL_FEATURES].to_numpy(dtype=float)).all():
        raise ValueError("causal feature output contains nonfinite values")

    maximum_difference = 0.0
    if features is not None:
        expected = features.sort_values("event_id")
        if list(rebuilt.event_id) != list(expected.event_id):
            raise ValueError("saved and rebuilt feature rows do not align")
        maximum_difference = float(
            np.max(
                np.abs(
                    rebuilt.loc[:, MODEL_FEATURES].to_numpy(dtype=float)
                    - expected.loc[:, MODEL_FEATURES].to_numpy(dtype=float)
                ),
                initial=0.0,
            )
        )
        if maximum_difference > tolerance:
            raise ValueError(
                f"saved causal features differ from replay: {maximum_difference}"
            )

    return {
        "status": "passed",
        "devices": int(len(devices)),
        "events": int(len(raw)),
        "requests": int(raw.event_type.eq("authorization_request").sum()),
        "feature_rows": int(len(rebuilt)),
        "feature_count": len(MODEL_FEATURES),
        "maximum_replay_difference": maximum_difference,
        "tolerance": tolerance,
        "sha256": {
            "raw_events.csv": _sha256(raw_path),
            "device_splits.csv": _sha256(split_path),
            **(
                {"events_with_features.csv": _sha256(feature_path)}
                if feature_path.exists()
                else {}
            ),
        },
    }
