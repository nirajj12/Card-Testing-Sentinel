from __future__ import annotations

import json
from pathlib import Path

from card_testing_sentinel.features.specification_v3 import MODEL_FEATURES_V3
from card_testing_sentinel.ml.pbrss_v1_evaluation import build_freeze_manifest


def write(path: Path, content: str = "fixture\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def test_freeze_manifest_is_deterministic_and_timestamp_free(tmp_path: Path) -> None:
    data = tmp_path / "data/generated/post_blind_stress_v1"
    for name in ("raw_events.csv", "labels.csv", "features_v3_1.csv"):
        write(data / name)
    write(
        data / "manifest.json",
        json.dumps(
            {
                "events": 12,
                "authorization_requests": 4,
                "devices": 2,
                "attack_devices": 1,
                "legitimate_devices": 1,
                "merchants": 2,
                "scenarios": {"fixture": 2},
                "evaluated": False,
                "consumed": False,
            }
        ),
    )
    contract = json.dumps({"features": list(MODEL_FEATURES_V3)})
    files = {
        "configs/post_blind_stress_v1.yaml": "spec_version: fixture\n",
        "src/card_testing_sentinel/ml/pbrss_v1_generator.py": "fixture\n",
        "src/card_testing_sentinel/ml/pbrss_v1_evaluation.py": "fixture\n",
        "src/card_testing_sentinel/features/engine_v3.py": "fixture\n",
        "src/card_testing_sentinel/features/batch_v3.py": "fixture\n",
        "pipelines/generate_post_blind_stress_v1.py": "fixture\n",
        "pipelines/evaluate_pbrss_v1_once.py": "fixture\n",
        "artifacts/model_v3_1/risk_model_v3_1.joblib": "fixture\n",
        "artifacts/model_v3_1/metadata.json": "{}\n",
        "artifacts/model_v3_1/feature_contract.json": contract,
        "artifacts/policy_v2/operational_policy_v2.json": "{}\n",
    }
    for relative, content in files.items():
        write(tmp_path / relative, content)
    commit = "a" * 40
    first = build_freeze_manifest(tmp_path, machinery_freeze_commit=commit)
    second = build_freeze_manifest(tmp_path, machinery_freeze_commit=commit)
    assert first == second
    encoded = json.dumps(first, sort_keys=True)
    assert "created_at" not in encoded
    assert "timestamp" not in encoded
    assert first["counts"]["devices"] == 2
    assert first["pbrss_machinery_freeze_commit"] == commit
