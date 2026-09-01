"""Validate the generated dataset and print the EDA summary.

    python pipelines/validate_dataset.py

Exits non-zero when a gate fails. The fix for a failure is to change the
generator and regenerate -- never to drop rows.
"""

import json
import sys
from pathlib import Path

import pandas as pd

from card_testing_sentinel.features.batch import read_raw_events
from card_testing_sentinel.ml.generator import load_config
from card_testing_sentinel.ml.validation import DatasetValidator

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/generated/development"

if __name__ == "__main__":
    config = load_config(ROOT / "configs/training.yaml")
    report = DatasetValidator(config["gates"]).validate(
        read_raw_events(DATA / "raw_events.csv"),
        pd.read_csv(DATA / "labels.csv"),
        pd.read_csv(DATA / "features.csv"),
    )
    (DATA / "validation_report.json").write_text(
        json.dumps(report.as_dict(), indent=2, sort_keys=True, default=str) + "\n"
    )
    print(json.dumps(report.as_dict(), indent=2, sort_keys=True, default=str))
    sys.exit(0 if report.passed else 1)
