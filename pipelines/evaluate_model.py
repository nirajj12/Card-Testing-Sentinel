import json
from pathlib import Path

import joblib
import pandas as pd

from card_testing_sentinel.ml.evaluation import (
    evaluate_validation_rows,
    replay_operational_policy,
    summarize_sequential_decisions,
)

ROOT = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    model_path = ROOT / "artifacts/development/training/development_model.joblib"
    feature_path = ROOT / "data/development/events_with_features.csv"
    row_metrics = evaluate_validation_rows(model_path, feature_path)
    artifact = joblib.load(model_path)
    policy = json.loads(
        (ROOT / "artifacts/policy/operational_policy.json").read_text()
    )["policy"]
    raw = pd.read_csv(ROOT / "data/development/raw_events.csv")
    splits = pd.read_csv(ROOT / "data/development/device_splits.csv")
    validation_ids = set(splits.loc[splits.split.eq("validation"), "device_id"])
    decisions = replay_operational_policy(
        raw.loc[raw.device_id.isin(validation_ids)], artifact, policy
    )
    output = ROOT / "artifacts/development/evaluation"
    output.mkdir(parents=True, exist_ok=True)
    decisions.to_csv(output / "validation_decisions.csv", index=False)
    summary = {
        "row_metrics": row_metrics,
        "sequential_metrics": summarize_sequential_decisions(decisions),
        "blind_evidence_read": False,
    }
    (output / "validation_metrics.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n"
    )
    print(summary)
