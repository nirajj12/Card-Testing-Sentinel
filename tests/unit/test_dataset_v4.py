"""Unit tests for Dataset v4 generator and manifest verification."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import yaml

from card_testing_sentinel.ml.generator_v4 import (
    build_merchants_v4,
)

ROOT = Path(__file__).resolve().parents[2]


def test_merchants_v4_generation() -> None:
    config_path = ROOT / "configs/dataset_v4_1.yaml"
    config = yaml.safe_load(config_path.read_text())
    merchants = build_merchants_v4(config)
    assert len(merchants) == 20
    kinds = {m.kind for m in merchants}
    assert "subscription" in kinds
    assert "micro_payment" in kinds
    assert "high_ticket" in kinds


def test_dataset_v4_artifacts_exist_and_consistent() -> None:
    data_dir = ROOT / "data/generated/development_v4_1"
    assert (data_dir / "raw_events.csv").exists()
    assert (data_dir / "labels.csv").exists()
    assert (data_dir / "features_v3_1.csv").exists()
    assert (data_dir / "manifest.json").exists()

    manifest = json.loads((data_dir / "manifest.json").read_text())
    assert manifest["dataset_name"] == "development-v4.1"
    assert manifest["total_devices"] == 12000
    assert manifest["counterfactual_pairs_count"] == 20

    labels = pd.read_csv(data_dir / "labels.csv")
    assert len(labels) == 12000
    assert labels["label"].nunique() == 2
    assert "cross_device_weak_guest" in labels["scenario"].values
    assert "subscription_dunning_hard" in labels["scenario"].values
    assert labels["leakage_group_id"].notna().all()
    train_groups = set(labels.loc[labels.split.eq("train"), "leakage_group_id"])
    val_groups = set(labels.loc[labels.split.eq("validation"), "leakage_group_id"])
    assert train_groups.isdisjoint(val_groups)
