"""Validate the blind benchmark and report its distribution shift.

    python pipelines/validate_blind.py

Runs every integrity, independence, temporal and leakage gate, then writes a
FEATURE-ONLY shift report comparing development validation against blind.

No model is loaded and no policy is applied, so running this does not consume
the benchmark. Exits non-zero if any gate fails.
"""

import json
import sys
from pathlib import Path

import pandas as pd

from card_testing_sentinel.features.batch import read_raw_events
from card_testing_sentinel.ml.blind_generator import load_config
from card_testing_sentinel.ml.blind_validation import shift_report, validate_blind

ROOT = Path(__file__).resolve().parents[1]
BLIND = ROOT / "data/generated/blind"
DEV = ROOT / "data/generated/development"
OUT = ROOT / "artifacts/evaluation"

ENTRY_MODULES = (
    "card_testing_sentinel.ml.blind_generator",
    "card_testing_sentinel.ml.primitives",
)

if __name__ == "__main__":
    config = load_config(ROOT / "configs/blind.yaml")
    blind_raw = read_raw_events(BLIND / "raw_events.csv")
    blind_labels = pd.read_csv(BLIND / "labels.csv")
    blind_features = pd.read_csv(BLIND / "features.csv")
    dev_raw = read_raw_events(DEV / "raw_events.csv")
    dev_labels = pd.read_csv(DEV / "labels.csv")
    dev_features = pd.read_csv(DEV / "features.csv")

    report = validate_blind(
        ROOT,
        config,
        blind_raw,
        blind_labels,
        blind_features,
        dev_raw,
        dev_labels,
        ENTRY_MODULES,
    )
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = str(config["blind_version"]).replace(".", "_")
    (OUT / f"blind_validation_report_{stamp}.json").write_text(
        json.dumps(report.as_dict(), indent=2, sort_keys=True, default=str) + "\n"
    )

    shift = shift_report(
        dev_features.loc[dev_features.split.eq("validation")], blind_features
    )
    shift.to_csv(OUT / f"blind_shift_report_{stamp}.csv", index=False)

    print(
        json.dumps(
            {
                "status": report.as_dict()["status"],
                "failures": report.failures,
                "warnings": report.warnings,
                "temporal": report.summary.get("temporal"),
                "merchants": report.summary.get("merchants"),
            },
            indent=2,
            sort_keys=True,
            default=str,
        )
    )
    sys.exit(0 if report.passed else 1)
