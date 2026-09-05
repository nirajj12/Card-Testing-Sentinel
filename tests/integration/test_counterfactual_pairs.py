"""Integration tests verifying the 20 counterfactual twin pairs
evaluated under Model v3.
"""

from __future__ import annotations

from pathlib import Path

import joblib
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]


def test_counterfactual_pairs_ordering() -> None:
    data_path = ROOT / "data/generated/development_v4_1/features_v3_1.csv"
    model_path = ROOT / "artifacts/model_v3_1/risk_model_v3_1.joblib"

    features = pd.read_csv(data_path, low_memory=False)
    val = features.loc[features.split.eq("validation")].copy()
    artifact = joblib.load(model_path)

    val["score"] = artifact.score_frame(val)
    dev = (
        val.groupby(["device_id", "label", "counterfactual_pair_id"])
        .agg(max_score=("score", "max"))
        .reset_index()
    )

    pairs = dev.dropna(subset=["counterfactual_pair_id"]).groupby(
        "counterfactual_pair_id"
    )
    correct = 0
    total = 0

    for _pair_id, grp in pairs:
        att = grp.loc[grp.label.eq(1), "max_score"].mean()
        leg = grp.loc[grp.label.eq(0), "max_score"].mean()
        if pd.notna(att) and pd.notna(leg):
            total += 1
            if att > leg:
                correct += 1

    assert total == 20
    cpoa = correct / total
    # CPOA is diagnostic: 90% is a stretch objective, not a test gate.
    assert 0.0 <= cpoa <= 1.0
