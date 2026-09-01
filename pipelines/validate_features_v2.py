"""Run the leakage gates and per-feature diagnostics on Feature Contract v2.

    python pipelines/validate_features_v2.py

Loads no model, trains nothing (the only estimator is the shuffled-label
probe). Exits non-zero if any hard gate fails -- and if one does, Model v2
training must not start.
"""

import json
import sys
from pathlib import Path

import pandas as pd

from card_testing_sentinel.features.specification_v2 import NEW_IN_V2
from card_testing_sentinel.ml.validation_features_v2 import (
    correlation_pairs,
    feature_distributions,
    scenario_feature_table,
    segment_table,
    validate_features_v2,
)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/generated/development_v3"
OUT = ROOT / "artifacts/evaluation"

if __name__ == "__main__":
    features = pd.read_csv(DATA / "features_v2.csv")
    report = validate_features_v2(features)

    OUT.mkdir(parents=True, exist_ok=True)
    feature_distributions(features).to_csv(
        OUT / "features_v2_distributions.csv", index=False
    )
    scenario_feature_table(features, NEW_IN_V2).to_csv(
        OUT / "features_v2_by_scenario.csv", index=False
    )
    segment_table(features, NEW_IN_V2).to_csv(
        OUT / "features_v2_by_segment.csv", index=False
    )
    correlation_pairs(features).to_csv(
        OUT / "features_v2_correlations.csv", index=False
    )
    (OUT / "features_v2_validation_report.json").write_text(
        json.dumps(report.as_dict(), indent=2, sort_keys=True, default=str) + "\n"
    )

    print(
        json.dumps(
            {
                "status": report.as_dict()["status"],
                "failures": report.failures,
                "warnings": report.warnings,
                "shuffled_label_roc_auc": report.summary.get("shuffled_label_roc_auc"),
                "univariate_max_f1_new_features": report.summary.get(
                    "univariate_max_f1_new_features"
                ),
                "overlap_coefficient": report.summary.get("overlap_coefficient"),
                "customer_missingness": report.summary.get("customer_missingness"),
            },
            indent=2,
            sort_keys=True,
            default=str,
        )
    )
    sys.exit(0 if report.passed else 1)
