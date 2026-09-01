"""Rebuild the Dataset v3 feature matrix under Feature Contract v2.

    python pipelines/build_features_v2.py

Reads the FROZEN Dataset v3 raw events and labels and writes
`features_v2.csv` beside them. The v1 projection (`features.csv`) is left
untouched, so the frozen Model v1 can still be scored on it.

No model is loaded and nothing is trained here.
"""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from card_testing_sentinel.features.batch import read_raw_events
from card_testing_sentinel.features.batch_v2 import build_feature_table_v2
from card_testing_sentinel.features.specification_v2 import (
    FEATURE_CONTRACT_V2_VERSION,
    MODEL_FEATURES_V2,
    MODEL_FEATURES_V2_SHA256,
    validate_feature_contract_v2,
)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/generated/development_v3"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    validate_feature_contract_v2()
    raw = read_raw_events(DATA / "raw_events.csv")
    labels = pd.read_csv(DATA / "labels.csv")

    features = build_feature_table_v2(raw, labels)
    features.to_csv(DATA / "features_v2.csv", index=False, lineterminator="\n")

    manifest = {
        "feature_contract_version": FEATURE_CONTRACT_V2_VERSION,
        "feature_contract_sha256": MODEL_FEATURES_V2_SHA256,
        "feature_count": len(MODEL_FEATURES_V2),
        "features": list(MODEL_FEATURES_V2),
        "rows": int(len(features)),
        "built_utc": datetime.now(UTC).isoformat(),
        "source_raw_events_sha256": sha256_file(DATA / "raw_events.csv"),
        "source_labels_sha256": sha256_file(DATA / "labels.csv"),
        "features_v2_sha256": sha256_file(DATA / "features_v2.csv"),
        "model_trained": False,
        "blind_evaluated": False,
        "note": (
            "Feature Contract v2 projection of the frozen Dataset v3 raw "
            "events. The v1 projection features.csv is unchanged and still "
            "serves the frozen 28-feature Model v1."
        ),
    }
    (DATA / "features_v2_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps({k: v for k, v in manifest.items() if k != "features"}, indent=2))
