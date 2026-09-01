"""Generate Blind v2 twice, require byte identity, and write no scores/decisions."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from card_testing_sentinel.features.batch_v2 import build_feature_table_v2
from card_testing_sentinel.ml.blind_v2_generator import (
    generate_blind_v2_bundle,
    load_config,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs/blind_v2.yaml"
SPEC = ROOT / "docs/blind_v2_spec.md"
DATASET_V3_MANIFEST = ROOT / "data/generated/development_v3/manifest.json"
OUTPUT = ROOT / "data/generated/blind_v2"
FREEZE = ROOT / "artifacts/evaluation/blind_v2_freeze_manifest.json"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def csv_bytes(frame: pd.DataFrame) -> bytes:
    return frame.to_csv(index=False, lineterminator="\n").encode()


def one_generation(config: dict) -> dict[str, bytes | dict]:
    bundle = generate_blind_v2_bundle(config, CONFIG, SPEC, DATASET_V3_MANIFEST)
    raw_for_features = bundle["raw_events"].copy()
    raw_for_features["split"] = "blind_v2"
    features = build_feature_table_v2(raw_for_features, bundle["labels"])
    raw_bytes = csv_bytes(bundle["raw_events"])
    label_bytes = csv_bytes(bundle["labels"])
    feature_bytes = csv_bytes(features)
    manifest = {
        **bundle["manifest"],
        "raw_events_sha256": sha256_bytes(raw_bytes),
        "labels_sha256": sha256_bytes(label_bytes),
        "features_v2_sha256": sha256_bytes(feature_bytes),
        "feature_rows": int(len(features)),
    }
    manifest_bytes = (
        json.dumps(manifest, indent=2, sort_keys=True, default=str) + "\n"
    ).encode()
    return {
        "raw_events.csv": raw_bytes,
        "labels.csv": label_bytes,
        "features_v2.csv": feature_bytes,
        "manifest.json": manifest_bytes,
        "manifest": manifest,
    }


def require_source_freeze() -> None:
    if not FREEZE.is_file():
        raise RuntimeError("freeze Blind v2 foundation and sources before generation")
    freeze = json.loads(FREEZE.read_text())
    if "foundation" not in freeze or "sources" not in freeze:
        raise RuntimeError("Blind v2 source freeze is incomplete")
    if freeze.get("evaluated") or freeze.get("consumed"):
        raise RuntimeError(
            "Blind v2 is already evaluated/consumed and cannot regenerate"
        )
    if "dataset" in freeze:
        raise RuntimeError("Blind v2 dataset is already frozen and cannot regenerate")


if __name__ == "__main__":
    require_source_freeze()
    config = load_config(CONFIG)
    first = one_generation(config)
    second = one_generation(config)
    names = ("raw_events.csv", "labels.csv", "features_v2.csv", "manifest.json")
    mismatches = [name for name in names if first[name] != second[name]]
    if mismatches:
        raise RuntimeError(f"Blind v2 is not byte deterministic: {mismatches}")

    OUTPUT.mkdir(parents=True, exist_ok=True)
    for name in names:
        (OUTPUT / name).write_bytes(first[name])
    reproducibility = {
        "blind_version": "v2",
        "runs": 2,
        "clean_in_memory_generators": 2,
        "byte_identical": True,
        "files": {name: sha256_bytes(first[name]) for name in names},
        "contains_model_scores": False,
        "contains_policy_decisions": False,
        "evaluated": False,
        "consumed": False,
    }
    (OUTPUT / "reproducibility.json").write_text(
        json.dumps(reproducibility, indent=2, sort_keys=True) + "\n"
    )
    manifest = first["manifest"]
    print(
        json.dumps(
            {
                key: manifest[key]
                for key in (
                    "blind_version",
                    "devices",
                    "actors",
                    "customers_observed",
                    "events",
                    "requests",
                    "attack_devices",
                    "realized_attack_device_fraction",
                    "customer_id_presence",
                    "window",
                    "evaluated",
                    "consumed",
                )
            },
            indent=2,
            sort_keys=True,
        )
    )
