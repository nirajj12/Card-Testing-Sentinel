from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[4]
MODEL_FEATURES = tuple(
    yaml.safe_load((ROOT / "configs/v2/features.yaml").read_text())["features"]
)

FORBIDDEN_FEATURE_TERMS = (
    "label",
    "population",
    "subtype",
    "scenario",
    "result",
    "outcome",
    "split",
    "device_id",
    "session_id",
    "fingerprint",
    "completion_future",
)
