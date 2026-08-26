from pathlib import Path

import pandas as pd

from card_testing_sentinel.ml.eda import training_eda

ROOT = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    data_dir = ROOT / "data/development"
    features = pd.read_csv(data_dir / "events_with_features.csv")
    raw = pd.read_csv(data_dir / "raw_events.csv")
    training_ids = set(features.loc[features.split.eq("train"), "device_id"])
    result = training_eda(
        features.loc[features.device_id.isin(training_ids)],
        raw.loc[raw.device_id.isin(training_ids)],
        ROOT / "artifacts/development/eda",
    )
    print(result)
