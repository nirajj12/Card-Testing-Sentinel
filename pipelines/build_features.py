from pathlib import Path

import pandas as pd

from card_testing_sentinel.features.batch import replay_training_events

ROOT = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    data_dir = ROOT / "data/development"
    raw = pd.read_csv(data_dir / "raw_events.csv")
    devices = pd.read_csv(data_dir / "device_splits.csv")
    split_map = devices.set_index("device_id")["split"]
    parts = []
    for split, events in raw.assign(split=raw.device_id.map(split_map)).groupby(
        "split", sort=True
    ):
        features, _latencies = replay_training_events(events.drop(columns="split"))
        features["split"] = split
        parts.append(features)
    pd.concat(parts, ignore_index=True).to_csv(
        data_dir / "events_with_features.csv", index=False, float_format="%.12g"
    )
