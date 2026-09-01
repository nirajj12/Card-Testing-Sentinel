"""Validate Dataset v3 against every declared gate.

    python pipelines/validate_dataset_v3.py

Loads no model and computes no metric. Exits non-zero if any gate fails.
"""

import json
import sys
from pathlib import Path

import pandas as pd

from card_testing_sentinel.features.batch import read_raw_events
from card_testing_sentinel.ml.generator_v3 import load_config
from card_testing_sentinel.ml.validation_v3 import validate_dataset_v3

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/generated/development_v3"
OUT = ROOT / "artifacts/evaluation"

if __name__ == "__main__":
    config = load_config(ROOT / "configs/dataset_v3.yaml")
    raw = read_raw_events(DATA / "raw_events.csv")
    labels = pd.read_csv(DATA / "labels.csv")
    features = pd.read_csv(DATA / "features.csv")

    report = validate_dataset_v3(config, raw, labels, features)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "dataset_v3_validation_report.json").write_text(
        json.dumps(report.as_dict(), indent=2, sort_keys=True, default=str) + "\n"
    )
    summary = report.summary
    print(
        json.dumps(
            {
                "status": report.as_dict()["status"],
                "failures": report.failures,
                "warnings": report.warnings,
                "customer_structure": summary.get("customer_structure"),
                "customer_id_presence": summary.get("customer_id_presence"),
                "long_horizon": summary.get("long_horizon"),
                "label_bookkeeping": summary.get("label_bookkeeping"),
                "decline_rate": {
                    k: v
                    for k, v in (summary.get("decline_rate") or {}).items()
                    if k != "note"
                },
                "temporal_separation_seconds": summary.get(
                    "temporal_separation_seconds"
                ),
            },
            indent=2,
            sort_keys=True,
            default=str,
        )
    )
    sys.exit(0 if report.passed else 1)
