"""Generate the frozen blind benchmark (v1).

    python pipelines/generate_blind.py

Refuses to run if the benchmark has already been evaluated -- a consumed
benchmark must never be regenerated. Writes raw events, labels and a
provenance-only manifest, then replays the events through the runtime
FeatureEngine to build features.

This script computes NO model score and NO policy decision.
"""

import json
from pathlib import Path

import pandas as pd

from card_testing_sentinel.features.batch import build_feature_table, read_raw_events
from card_testing_sentinel.ml.blind_generator import (
    assert_not_consumed,
    generate_blind_bundle,
    load_config,
    write_blind,
)

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data/generated/blind"
FREEZE = ROOT / "artifacts/evaluation/blind_freeze_manifest.json"

if __name__ == "__main__":
    assert_not_consumed(FREEZE)
    config = load_config(ROOT / "configs/blind.yaml")
    bundle = generate_blind_bundle(
        config,
        ROOT / "docs/blind_spec.md",
        ROOT / "data/generated/development/manifest.json",
    )
    manifest = write_blind(bundle, OUTPUT)

    raw = read_raw_events(OUTPUT / "raw_events.csv")
    raw["split"] = "blind"
    labels = pd.read_csv(OUTPUT / "labels.csv")
    features = build_feature_table(raw, labels)
    features.to_csv(OUTPUT / "features.csv", index=False, lineterminator="\n")

    print(
        json.dumps(
            {
                k: v
                for k, v in manifest.items()
                if k
                not in (
                    "scenario_devices",
                    "scenario_requests",
                    "merchant_kind_devices",
                )
            },
            indent=2,
            sort_keys=True,
            default=str,
        )
    )
