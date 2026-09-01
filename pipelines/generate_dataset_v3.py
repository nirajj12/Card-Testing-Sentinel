"""Generate Dataset v3 -- the final development dataset.

    python pipelines/generate_dataset_v3.py

Writes data/generated/development_v3/{raw_events,labels,features}.csv and
manifest.json. Dataset V2 in data/generated/development/ is untouched, and
no model is trained or loaded here.
"""

import json
from pathlib import Path

import pandas as pd

from card_testing_sentinel.features.batch import build_feature_table, read_raw_events
from card_testing_sentinel.ml.generator_v3 import (
    build_manifest,
    generate_dataset_v3,
    load_config,
)

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data/generated/development_v3"

if __name__ == "__main__":
    config = load_config(ROOT / "configs/dataset_v3.yaml")
    bundle = generate_dataset_v3(config)
    manifest = build_manifest(config, bundle)

    OUTPUT.mkdir(parents=True, exist_ok=True)
    bundle["raw_events"].to_csv(
        OUTPUT / "raw_events.csv", index=False, lineterminator="\n"
    )
    bundle["labels"].to_csv(OUTPUT / "labels.csv", index=False, lineterminator="\n")

    raw = read_raw_events(OUTPUT / "raw_events.csv")
    labels = pd.read_csv(OUTPUT / "labels.csv")
    features = build_feature_table(raw, labels)
    features.to_csv(OUTPUT / "features.csv", index=False, lineterminator="\n")

    (OUTPUT / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True, default=str) + "\n"
    )
    print(
        json.dumps(
            {
                k: v
                for k, v in manifest.items()
                if k not in ("scenario_devices", "merchant_kind_devices")
            },
            indent=2,
            sort_keys=True,
            default=str,
        )
    )
