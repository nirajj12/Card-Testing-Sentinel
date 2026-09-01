"""Generate the synthetic development dataset (train + validation).

    python pipelines/generate_dataset.py

Writes data/generated/development/{raw_events,labels,split_assignments}.csv
and manifest.json. The blind evaluation set is NOT produced here.
"""

import json
from pathlib import Path

from card_testing_sentinel.ml.generator import (
    generate_development_dataset,
    load_config,
    write_dataset,
)

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data/generated/development"

if __name__ == "__main__":
    config = load_config(ROOT / "configs/training.yaml")
    manifest = write_dataset(generate_development_dataset(config), OUTPUT)
    print(json.dumps(manifest, indent=2, sort_keys=True, default=str))
