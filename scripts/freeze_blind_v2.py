"""Three-stage byte freeze for Blind v2; never loads a model or policy."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "artifacts/evaluation/blind_v2_freeze_manifest.json"

FOUNDATION_FILES = {
    "dataset_v3_raw_sha256": "data/generated/development_v3/raw_events.csv",
    "dataset_v3_labels_sha256": "data/generated/development_v3/labels.csv",
    "dataset_v3_features_v2_sha256": "data/generated/development_v3/features_v2.csv",
    "feature_contract_v2_artifact_sha256": "artifacts/model_v2/feature_contract.json",
    "feature_contract_v2_source_sha256": (
        "src/card_testing_sentinel/features/specification_v2.py"
    ),
    "feature_engine_v2_sha256": "src/card_testing_sentinel/features/engine_v2.py",
    "model_v2_sha256": "artifacts/model_v2/risk_model_v2.joblib",
    "model_v2_metadata_sha256": "artifacts/model_v2/metadata.json",
    "policy_v2_config_sha256": "configs/policy_v2.yaml",
    "policy_v2_artifact_sha256": "artifacts/policy_v2/operational_policy_v2.json",
    "blind_v1_1_freeze_sha256": "artifacts/evaluation/blind_freeze_manifest.json",
}
SOURCE_FILES = {
    "spec_sha256": "docs/blind_v2_spec.md",
    "config_sha256": "configs/blind_v2.yaml",
    "generator_sha256": "src/card_testing_sentinel/ml/blind_v2_generator.py",
    "validator_sha256": "src/card_testing_sentinel/ml/blind_v2_validation.py",
    "generation_pipeline_sha256": "pipelines/generate_blind_v2.py",
    "validation_pipeline_sha256": "pipelines/validate_blind_v2.py",
    "neutral_primitives_sha256": "src/card_testing_sentinel/ml/primitives.py",
    "merchant_mechanics_sha256": "src/card_testing_sentinel/ml/merchants.py",
    "feature_projection_sha256": "src/card_testing_sentinel/features/batch_v2.py",
}
DATASET_FILES = {
    "raw_events_sha256": "data/generated/blind_v2/raw_events.csv",
    "labels_sha256": "data/generated/blind_v2/labels.csv",
    "features_v2_sha256": "data/generated/blind_v2/features_v2.csv",
    "manifest_sha256": "data/generated/blind_v2/manifest.json",
    "reproducibility_sha256": "data/generated/blind_v2/reproducibility.json",
    "validation_report_sha256": "artifacts/evaluation/blind_v2_validation_report.json",
    "shift_report_sha256": "artifacts/evaluation/blind_v2_shift_report.csv",
}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_manifest() -> dict:
    if MANIFEST.is_file():
        return json.loads(MANIFEST.read_text())
    return {
        "blind_version": "v2",
        "evaluated": False,
        "consumed": False,
    }


def freeze(stage: str) -> dict:
    manifest = load_manifest()
    if manifest.get("evaluated") or manifest.get("consumed"):
        raise RuntimeError("Blind v2 is already evaluated/consumed")
    mapping = {
        "foundation": FOUNDATION_FILES,
        "sources": SOURCE_FILES,
        "dataset": DATASET_FILES,
    }[stage]
    missing = [name for name in mapping.values() if not (ROOT / name).is_file()]
    if missing:
        raise RuntimeError(f"cannot freeze {stage}; missing {missing}")
    if stage == "sources" and "foundation" not in manifest:
        raise RuntimeError("freeze foundation before Blind v2 sources")
    if stage == "dataset":
        if "sources" not in manifest:
            raise RuntimeError("freeze Blind v2 sources before dataset")
        dataset_manifest = json.loads(
            (ROOT / "data/generated/blind_v2/manifest.json").read_text()
        )
        validation = json.loads(
            (ROOT / "artifacts/evaluation/blind_v2_validation_report.json").read_text()
        )
        if validation.get("status") != "passed":
            raise RuntimeError("Blind v2 validation has not passed")
        if any(dataset_manifest.get(key) for key in ("evaluated", "consumed")):
            raise RuntimeError("Blind v2 manifest is not unevaluated/unconsumed")
    section = {key: sha256_file(ROOT / name) for key, name in mapping.items()}
    section["files"] = dict(mapping)
    section["frozen_utc"] = datetime.now(UTC).isoformat()
    if stage == "sources" and manifest.get("sources") != section:
        previous = manifest.get("sources")
        if previous:
            manifest.setdefault("source_revision_history", []).append(
                {
                    **previous,
                    "reason": (
                        "Pre-evaluation implementation correction. Source/config "
                        "validation found an interface or dataframe-indexing defect; "
                        "no model score, policy decision, or performance result ran."
                    ),
                }
            )
    manifest[stage] = section
    manifest["blind_version"] = "v2"
    manifest["evaluated"] = False
    manifest["consumed"] = False
    manifest["contains_model_scores"] = False
    manifest["contains_policy_decisions"] = False
    manifest["note"] = (
        "Blind v2 is frozen but unevaluated. Phase 13 may evaluate it once; "
        "after any result is observed it must be marked consumed."
    )
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return section


def verify() -> list[str]:
    manifest = load_manifest()
    drift = []
    for stage in ("foundation", "sources", "dataset"):
        section = manifest.get(stage)
        if not section:
            continue
        for key, name in section["files"].items():
            path = ROOT / name
            if not path.is_file():
                drift.append(f"{stage}.{key}: {name} missing")
            elif sha256_file(path) != section[key]:
                drift.append(f"{stage}.{key}: {name} changed")
    return drift


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=("foundation", "sources", "dataset"))
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.verify:
        problems = verify()
        print(json.dumps({"ok": not problems, "drift": problems}, indent=2))
        raise SystemExit(1 if problems else 0)
    if not args.stage:
        raise SystemExit("pass --stage foundation|sources|dataset or --verify")
    print(json.dumps(freeze(args.stage), indent=2, sort_keys=True))
