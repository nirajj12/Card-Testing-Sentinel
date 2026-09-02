"""Generate Dataset v4 -- Post-Blind Development Dataset.

    python pipelines/generate_dataset_v4.py

Writes data/generated/development_v4_1/{raw_events,labels,features_v3_1}.csv and
manifest.json. Preserves Dataset v2 and v3 completely untouched.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from card_testing_sentinel.features.batch import read_raw_events
from card_testing_sentinel.features.batch_v3 import build_feature_table_v3
from card_testing_sentinel.ml.generator_v4 import (
    build_manifest_v4,
    generate_dataset_v4,
    load_config,
)

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data/generated/development_v4_1"


def main() -> None:
    config = load_config(ROOT / "configs/dataset_v4_1.yaml")
    print("Generating Dataset v4 raw events and labels...")
    bundle = generate_dataset_v4(config)
    manifest = build_manifest_v4(config, bundle)

    OUTPUT.mkdir(parents=True, exist_ok=True)
    raw_path = OUTPUT / "raw_events.csv"
    labels_path = OUTPUT / "labels.csv"
    features_path = OUTPUT / "features_v3_1.csv"
    manifest_path = OUTPUT / "manifest.json"

    bundle["raw_events"].to_csv(raw_path, index=False, lineterminator="\n")
    bundle["labels"].to_csv(labels_path, index=False, lineterminator="\n")
    print(f"Wrote raw events ({len(bundle['raw_events'])} rows) and labels ({len(bundle['labels'])} rows).")

    print("Replaying events through FeatureEngineV3...")
    raw = read_raw_events(raw_path)
    labels = pd.read_csv(labels_path)
    features = build_feature_table_v3(raw, labels)
    features.to_csv(features_path, index=False, lineterminator="\n")
    print(f"Wrote features table ({len(features)} rows, {len(features.columns)} columns).")

    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True, default=str) + "\n")
    print("Dataset v4 generation complete!")


if __name__ == "__main__":
    main()
