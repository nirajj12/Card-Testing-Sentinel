"""Validate and report Blind v2 without loading a model or invoking a policy."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

from card_testing_sentinel.features.batch import read_raw_events
from card_testing_sentinel.ml.blind_v2_generator import load_config
from card_testing_sentinel.ml.blind_v2_validation import (
    feature_shift_report,
    validate_blind_v2,
)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/generated/blind_v2"
OUT = ROOT / "artifacts/evaluation"
ENTRY_MODULES = (
    "card_testing_sentinel.ml.blind_v2_generator",
    "card_testing_sentinel.ml.primitives",
    "card_testing_sentinel.ml.merchants",
)


if __name__ == "__main__":
    config = load_config(ROOT / "configs/blind_v2.yaml")
    raw = read_raw_events(DATA / "raw_events.csv")
    labels = pd.read_csv(DATA / "labels.csv")
    features = pd.read_csv(DATA / "features_v2.csv")
    development_raw = read_raw_events(
        ROOT / "data/generated/development_v3/raw_events.csv"
    )
    blind_v1_raw = read_raw_events(ROOT / "data/generated/blind/raw_events.csv")
    development_features = pd.read_csv(
        ROOT / "data/generated/development_v3/features_v2.csv"
    )

    report = validate_blind_v2(
        root=ROOT,
        config=config,
        raw=raw,
        labels=labels,
        features=features,
        development_raw=development_raw,
        blind_v1_raw=blind_v1_raw,
        generator_entries=ENTRY_MODULES,
    )
    shift = feature_shift_report(
        development_features.loc[development_features.split.eq("validation")],
        features,
    )
    report.summary["shift_summary"] = {
        "features": int(len(shift)),
        "median_psi": round(float(shift.psi.median()), 4),
        "max_psi": round(float(shift.psi.max()), 4),
        "median_ks": round(float(shift.ks.median()), 4),
        "median_overlap": round(float(shift.overlap_coefficient.median()), 4),
        "largest_shifts": shift.head(10).to_dict("records"),
    }
    report.summary["composition_shift"] = {
        "blind_v2_customer_id_request_share": round(
            float(
                raw.loc[raw.event_type.eq("authorization_request"), "customer_id"]
                .notna()
                .mean()
            ),
            4,
        ),
        "dataset_v3_customer_id_request_share": round(
            float(development_features.customer_id_present.mean()), 4
        ),
        "blind_v2_merchant_device_share": {
            str(key): round(float(value), 4)
            for key, value in (
                labels.drop_duplicates("device_id").merchant_kind.value_counts(
                    normalize=True
                )
            ).items()
        },
        "blind_v2_scenario_device_share": {
            str(key): round(float(value), 4)
            for key, value in (
                labels.drop_duplicates("device_id").scenario.value_counts(
                    normalize=True
                )
            ).items()
        },
    }
    OUT.mkdir(parents=True, exist_ok=True)
    report_path = OUT / "blind_v2_validation_report.json"
    shift_path = OUT / "blind_v2_shift_report.csv"
    report_path.write_text(
        json.dumps(report.as_dict(), indent=2, sort_keys=True, default=str) + "\n"
    )
    shift.to_csv(shift_path, index=False, lineterminator="\n")
    print(
        json.dumps(
            {
                "status": "passed" if report.passed else "failed",
                "failures": report.failures,
                "warnings": report.warnings,
                "temporal": report.summary.get("temporal"),
                "behavioral_requirements": report.summary.get(
                    "behavioral_requirements"
                ),
                "shift_summary": report.summary.get("shift_summary"),
                "evaluated": False,
                "consumed": False,
            },
            indent=2,
            sort_keys=True,
            default=str,
        )
    )
    sys.exit(0 if report.passed else 1)
