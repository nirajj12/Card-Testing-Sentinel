"""Verify active frozen Model v3.1 integration without rescoring PBRSS."""

from __future__ import annotations

import json
from pathlib import Path

from verify_release import verify as verify_historical_v2

from card_testing_sentinel.common.config import load_config
from card_testing_sentinel.common.integrity import sha256_file
from card_testing_sentinel.features.engine_v3 import FeatureEngineV3
from card_testing_sentinel.features.specification_v3 import (
    MODEL_FEATURES_V3,
    MODEL_FEATURES_V3_SHA256,
)
from card_testing_sentinel.modeling.registry import ArtifactRegistry

ROOT = Path(__file__).resolve().parents[1]


def verify() -> list[str]:
    errors: list[str] = []

    def check(condition: bool, message: str) -> None:
        if not condition:
            errors.append(message)

    app = load_config(ROOT / "configs/app.yaml")
    check(
        app.get("runtime_manifest_path") == "configs/runtime_v3_1.yaml",
        "application does not select the v3.1 runtime manifest",
    )
    check(
        app.get("database_path") == "data/runtime/live_state_v3_1.sqlite3",
        "application does not use the isolated v3.1 database",
    )
    check(
        app.get("database_path") != "data/runtime/live_state_v2.sqlite3",
        "v3.1 runtime aliases the historical v2 database",
    )

    historical_errors = verify_historical_v2()
    errors.extend(f"historical v2: {error}" for error in historical_errors)

    try:
        registry = ArtifactRegistry.load(
            ROOT, manifest_path=ROOT / "configs/runtime_v3_1.yaml"
        )
    except Exception as error:
        errors.append(f"v3.1 registry failed validation: {error}")
        return errors

    runtime = registry.runtime
    expected_hashes = {
        "model_artifact_path": (
            "093254b63674f50b62caf5eddeaeba47d79f9327902e2567ffed75418a59b1e4"
        ),
        "feature_contract_artifact_path": (
            "522aa6327617bfed687bd2f0955405b5f63f6595fb0c86da9077b4442af554a8"
        ),
        "model_metadata_path": (
            "0c6c4f1f30b4e585022189bfdb10e4bf7c6d1efbe646abd1ec5fbdd4dca3592f"
        ),
        "feature_spec_path": (
            "9f07a99cb2717c361331ab8c6d26df9b28098366b0d9cc25108ed897baeeff4d"
        ),
        "policy_artifact_path": (
            "8e874ef83085b9bac063c3b0ac3044bb3c171071d00bf2db44c0390d944fe74c"
        ),
        "evaluation_result_manifest_path": (
            "3fd407689b1fd8a2248780fad8258a2629e82a928fced9026afc76b626cd0502"
        ),
        "evaluation_freeze_manifest_path": (
            "674268d2d7ac3c313b2d2ca8cd4c16a20f70c65c2e1887d4d8fbaaba0d6f3f78"
        ),
    }
    for path_field, expected in expected_hashes.items():
        check(
            sha256_file(ROOT / runtime[path_field]) == expected,
            f"frozen hash mismatch: {path_field}",
        )

    summary = registry.system_summary()
    check(
        runtime["version"] == "postblind-v3.1-prototype-runtime",
        "runtime identity mismatch",
    )
    check(registry.model.available, "Model v3.1 is unavailable")
    check(
        registry.feature_engine_class is FeatureEngineV3,
        "runtime is not bound to FeatureEngineV3",
    )
    check(
        registry.model_features == MODEL_FEATURES_V3, "runtime feature order mismatch"
    )
    check(
        registry.feature_contract_sha256 == MODEL_FEATURES_V3_SHA256,
        "runtime semantic feature hash mismatch",
    )
    check(summary["model_family"] == "hist_gradient_boosting", "model family mismatch")
    check(summary["model_candidate"] == "hist_gb_2", "model candidate mismatch")
    check(summary["calibration"] == "sigmoid", "calibration mismatch")
    check(summary["policy_version"] == "validation-selected-v2", "policy mismatch")
    check(summary["evaluation_version"] == "pbrss-v1", "evaluation identity mismatch")
    check(summary["evaluation_consumed"] is True, "PBRSS is not recorded as consumed")
    check(summary["evaluation_conclusion"] == "MIXED", "PBRSS conclusion mismatch")
    check(
        summary["production_ready"] is False,
        "runtime incorrectly claims production readiness",
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
                "runtime": "postblind-v3.1-prototype-runtime",
                "model": "model-v3.1",
                "features": 44,
                "policy": "validation-selected-v2",
                "evaluation": "pbrss-v1",
                "evaluation_conclusion": "MIXED",
                "runtime_stage": "evaluated_prototype_candidate",
                "production_ready": False,
                "pbrss_rescored": False,
                "historical_v2_verified": True,
            },
            indent=2,
        )
    )
