"""Train development model candidates and freeze the selected one.

    python pipelines/train_model.py

Writes artifacts/model/{risk_model.joblib,metadata.json,feature_contract.json}
plus the CV and calibration comparison tables. Selection uses TRAIN
out-of-fold predictions only -- the validation split is not read here.
"""

import json
from pathlib import Path

from card_testing_sentinel.ml.training import train_development_model

ROOT = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    metadata = train_development_model(
        ROOT / "data/generated/development/features.csv",
        ROOT / "configs/training.yaml",
        ROOT / "artifacts/model",
    )
    print(
        json.dumps(
            {
                k: v
                for k, v in metadata.items()
                if k not in ("cross_validation", "calibration_comparison")
            },
            indent=2,
            sort_keys=True,
            default=str,
        )
    )
