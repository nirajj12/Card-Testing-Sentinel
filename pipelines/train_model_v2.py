"""Train the Model v2 development candidate on Dataset v3 train.

    python pipelines/train_model_v2.py

Selection and calibration use TRAIN out-of-fold predictions only; the
validation split is not read. Writes artifacts/model_v2/. Model v1 in
artifacts/model/ is untouched.
"""

import json
from pathlib import Path

from card_testing_sentinel.ml.training_v2 import train_model_v2

ROOT = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    result = train_model_v2(
        ROOT / "data/generated/development_v3/features_v2.csv",
        ROOT / "configs/training_v2.yaml",
        ROOT / "artifacts/model_v2",
    )
    metadata = result["metadata"]
    print(
        json.dumps(
            {
                k: v
                for k, v in metadata.items()
                if k not in ("calibration_bins", "environment")
            },
            indent=2,
            sort_keys=True,
            default=str,
        )
    )
    print("\n--- candidates (out-of-fold, train only) ---")
    print(
        result["comparison"][
            ["candidate", "family", "pr_auc", "roc_auc", "brier", "ece"]
        ].to_string(index=False)
    )
    print("\n--- calibration ---")
    print(
        result["calibration"][
            ["method", "pr_auc", "roc_auc", "brier", "log_loss", "ece"]
        ]
        .round(4)
        .to_string(index=False)
    )
    print("\n--- ablations ---")
    print(result["ablations"].to_string(index=False))
