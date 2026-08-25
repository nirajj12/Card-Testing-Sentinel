from pathlib import Path

import pandas as pd

from card_testing_sentinel.common.atomic_io import atomic_write_text
from card_testing_sentinel.v2.features.batch import replay_partitioned_events

ROOT = Path(__file__).resolve().parents[2]

if __name__ == "__main__":
    raw = pd.read_csv(ROOT / "data/v2/development/raw_events.csv")
    splits = pd.read_csv(ROOT / "data/v2/development/device_splits.csv")
    features = replay_partitioned_events(raw, splits)
    atomic_write_text(
        ROOT / "data/v2/development/events_with_features.csv",
        features.to_csv(index=False, lineterminator="\n", float_format="%.6f"),
    )
    print(f"Built {len(features)} causal precheck rows")
