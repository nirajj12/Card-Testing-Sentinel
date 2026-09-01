"""Replay generated raw events through the live FeatureEngine.

    python pipelines/build_features.py

Produces data/generated/development/features.csv. Feature values come only
from the runtime engine; labels are joined afterwards on device_id.
"""

from pathlib import Path

import pandas as pd

from card_testing_sentinel.features.batch import build_feature_table, read_raw_events

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/generated/development"

if __name__ == "__main__":
    raw = read_raw_events(DATA / "raw_events.csv")
    labels = pd.read_csv(DATA / "labels.csv")
    features = build_feature_table(raw, labels)
    features.to_csv(DATA / "features.csv", index=False, lineterminator="\n")
    print(
        {
            "rows": len(features),
            "splits": features.groupby("split").size().to_dict(),
            "label_rows": features.groupby("label").size().to_dict(),
        }
    )
