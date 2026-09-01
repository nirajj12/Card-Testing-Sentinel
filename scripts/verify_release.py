"""Verify the frozen v2 runtime selection and evidence integrity."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import sklearn

from card_testing_sentinel.common.config import load_config
from card_testing_sentinel.common.integrity import sha256_file
from card_testing_sentinel.features.specification_v2 import (
    FEATURE_CONTRACT_V2_VERSION,
    MODEL_FEATURES_V2,
    MODEL_FEATURES_V2_SHA256,
)
from card_testing_sentinel.modeling.registry import ArtifactRegistry

ROOT = Path(__file__).resolve().parents[1]


def _json(path: Path) -> dict:
    return json.loads(path.read_text())


def verify() -> list[str]:
    errors: list[str] = []

    def check(condition: bool, message: str) -> None:
        if not condition:
            errors.append(message)

    try:
        runtime = load_config(ROOT / "configs/runtime.yaml")["runtime"]
    except Exception as error:
        return [f"runtime manifest cannot be loaded: {error}"]

    required = (
        "feature_spec_path",
        "feature_contract_artifact_path",
        "model_artifact_path",
        "model_metadata_path",
        "policy_config_path",
        "policy_artifact_path",
        "policy_checksum_path",
        "evaluation_metrics_path",
        "evaluation_detection_path",
        "evaluation_family_metrics_path",
        "evaluation_consumption_path",
        "evaluation_result_hashes_path",
    )
    for field in required:
        check(field in runtime, f"runtime manifest is missing {field}")
        if field in runtime:
            check(
                (ROOT / runtime[field]).is_file(),
                f"required file is missing: {field}",
            )
    if errors:
        return errors

    check(runtime["version"] == "frozen-v2-runtime", "runtime version is not v2")
    check(
        runtime["feature_contract_version"] == FEATURE_CONTRACT_V2_VERSION,
        "feature-contract version mismatch",
    )
    check(runtime["feature_count"] == 39, "feature count is not 39")
    check(
        runtime["feature_contract_sha256"] == MODEL_FEATURES_V2_SHA256,
        "feature-contract hash mismatch",
    )

    contract = _json(ROOT / runtime["feature_contract_artifact_path"])
    check(
        tuple(contract.get("model_features", ())) == MODEL_FEATURES_V2,
        "ordered 39-feature artifact does not match source",
    )
    metadata = _json(ROOT / runtime["model_metadata_path"])
    check(metadata.get("model_version") == "model-v2", "model version mismatch")
    check(metadata.get("feature_count") == 39, "model metadata feature count mismatch")
    check(
        metadata.get("feature_contract_sha256") == MODEL_FEATURES_V2_SHA256,
        "model metadata contract hash mismatch",
    )
    check(
        metadata.get("selected_calibration") == "sigmoid",
        "calibration is not sigmoid",
    )
    check(
        sha256_file(ROOT / runtime["model_artifact_path"])
        == metadata.get("model_sha256"),
        "Model v2 hash mismatch",
    )

    checksum = (ROOT / runtime["policy_checksum_path"]).read_text().split()[0]
    check(
        sha256_file(ROOT / runtime["policy_artifact_path"]) == checksum,
        "Policy v2 checksum mismatch",
    )
    policy = load_config(ROOT / runtime["policy_config_path"])["policy"]
    check(policy.get("version") == runtime["policy_version"], "policy version mismatch")
    check(policy.get("family") == runtime["policy_family"], "policy family mismatch")

    consumption = _json(ROOT / runtime["evaluation_consumption_path"])
    metrics = _json(ROOT / runtime["evaluation_metrics_path"])
    freeze = _json(ROOT / "artifacts/evaluation/blind_v2_freeze_manifest.json")
    check(
        sha256_file(ROOT / runtime["model_metadata_path"])
        == freeze["foundation"]["model_v2_metadata_sha256"],
        "Model v2 metadata hash mismatch",
    )
    check(
        sha256_file(ROOT / runtime["feature_contract_artifact_path"])
        == freeze["foundation"]["feature_contract_v2_artifact_sha256"],
        "Feature Contract v2 artifact hash mismatch",
    )
    check(
        sha256_file(ROOT / runtime["evaluation_result_hashes_path"])
        == freeze["result_hash_manifest_sha256"],
        "Blind v2 result manifest hash mismatch",
    )
    for required_config in (
        "configs/blind_v2.yaml",
        "configs/dataset_v3.yaml",
        "configs/features_v2.yaml",
        "configs/policy_v2.yaml",
    ):
        check((ROOT / required_config).is_file(), f"missing {required_config}")
    check(
        sha256_file(ROOT / "configs/blind_v2.yaml")
        == freeze["sources"]["config_sha256"],
        "Blind v2 configuration hash mismatch",
    )
    check(consumption.get("consumed") is True, "Blind v2 is not consumed")
    check(consumption.get("evaluated") is True, "Blind v2 is not evaluated")
    check(consumption.get("post_blind_tuning") is False, "post-blind tuning recorded")
    check(
        metrics.get("status") == "official_one_time_blind_v2_evaluation",
        "Blind v2 status mismatch",
    )
    check(metrics.get("verdict") == "WEAK", "Blind v2 verdict mismatch")
    check(
        metrics.get("model_version") == runtime["model_version"],
        "evaluation model mismatch",
    )

    frozen_checks = {
        runtime["model_artifact_path"]: consumption["model_v2_sha256"],
        runtime["policy_artifact_path"]: consumption["policy_v2_artifact_sha256"],
        runtime["policy_config_path"]: consumption["policy_v2_config_sha256"],
        "src/card_testing_sentinel/features/specification_v2.py": consumption[
            "feature_contract_v2_source_sha256"
        ],
        "src/card_testing_sentinel/features/engine_v2.py": consumption[
            "feature_engine_v2_sha256"
        ],
        "src/card_testing_sentinel/ml/blind_v2_evaluation.py": consumption[
            "evaluation_module_sha256"
        ],
        "pipelines/evaluate_blind_v2_once.py": consumption[
            "evaluation_pipeline_sha256"
        ],
    }
    for name, expected in frozen_checks.items():
        check(sha256_file(ROOT / name) == expected, f"frozen hash mismatch: {name}")

    result_hashes = _json(ROOT / runtime["evaluation_result_hashes_path"])
    for label, path in result_hashes["files"].items():
        check(
            sha256_file(ROOT / path) == result_hashes["hashes"][label],
            f"Blind v2 result hash mismatch: {label}",
        )

    metrics_source = (ROOT / "src/card_testing_sentinel/api/metrics.py").read_text()
    replay_source = (ROOT / "src/card_testing_sentinel/api/replay.py").read_text()
    forbidden = (".score(", "evaluate_blind", "generate_blind")
    for token in forbidden:
        check(
            token not in metrics_source,
            f"metrics endpoint may rescore evidence: {token}",
        )
        check(
            token not in replay_source,
            f"replay endpoint may rescore evidence: {token}",
        )

    try:
        registry = ArtifactRegistry.load(ROOT)
        check(registry.feature_count == 39, "loaded registry is not 39-feature v2")
        check(registry.model.available, "Model v2 is unavailable")
    except Exception as error:
        errors.append(f"active runtime failed validation: {error}")

    check(sys.version_info[:2] == (3, 11), "runtime requires Python 3.11")
    check(np.__version__ == metadata["environment"]["numpy"], "NumPy version mismatch")
    check(
        sklearn.__version__ == metadata["environment"]["sklearn"],
        "scikit-learn version mismatch",
    )
    return errors


if __name__ == "__main__":
    failures = verify()
    if failures:
        print(json.dumps({"status": "failed", "errors": failures}, indent=2))
        raise SystemExit(1)
    print(
        json.dumps(
            {
                "status": "verified",
                "runtime": "frozen-v2-runtime",
                "model": "model-v2",
                "features": 39,
                "policy": "validation-selected-v2",
                "evaluation": "blind-v2",
                "verdict": "WEAK",
                "post_blind_tuning": False,
            },
            indent=2,
        )
    )
