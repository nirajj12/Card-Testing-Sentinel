"""Generate and freeze PBRSS-v1. Phase 3A builds but never runs this pipeline."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from card_testing_sentinel.features.batch_v3 import build_feature_table_v3
from card_testing_sentinel.ml.pbrss_v1_evaluation import build_freeze_manifest
from card_testing_sentinel.ml.pbrss_v1_generator import PBRSSV1Generator, build_manifest

ROOT = Path(__file__).resolve().parents[1]


if __name__ == "__main__":
    config = yaml.safe_load((ROOT / "configs/post_blind_stress_v1.yaml").read_text())
    bundle = PBRSSV1Generator(config).generate()
    output = ROOT / "data/generated/post_blind_stress_v1"
    output.mkdir(parents=True, exist_ok=False)
    raw, labels = bundle["raw_events"], bundle["labels"]
    features = build_feature_table_v3(raw, labels)
    raw.to_csv(output / "raw_events.csv", index=False, lineterminator="\n")
    labels.to_csv(output / "labels.csv", index=False, lineterminator="\n")
    features.to_csv(output / "features_v3_1.csv", index=False, lineterminator="\n")
    (output / "manifest.json").write_text(
        json.dumps(build_manifest(config, bundle), indent=2, sort_keys=True) + "\n"
    )
    build_freeze_manifest(
        ROOT, ROOT / "artifacts/evaluation/pbrss_v1_freeze_manifest.json"
    )
