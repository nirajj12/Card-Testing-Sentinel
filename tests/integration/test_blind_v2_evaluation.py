"""Pre-score contracts for the irreversible Phase 13 evaluator."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import numpy as np
import pandas as pd

from card_testing_sentinel.ml.blind_v2_evaluation import (
    FIXED_THRESHOLDS,
    detection_group,
    threshold_diagnostics,
    verify_pre_evaluation,
    wilson_interval,
)

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src/card_testing_sentinel/ml/blind_v2_evaluation.py"


def test_lifecycle_is_pristine_before_scoring_and_consumed_afterward():
    freeze = json.loads(
        (ROOT / "artifacts/evaluation/blind_v2_freeze_manifest.json").read_text()
    )
    consumption = ROOT / "artifacts/evaluation/blind_v2_consumption.json"
    if not consumption.exists():
        result = verify_pre_evaluation(ROOT)
        assert result["status"] == "passed"
        assert freeze["evaluated"] is False
        assert freeze["consumed"] is False
    else:
        record = json.loads(consumption.read_text())
        assert freeze["evaluated"] is True
        assert freeze["consumed"] is True
        assert record["evaluated"] is True
        assert record["consumed"] is True
        assert record["post_blind_tuning"] is False


def test_evaluator_has_no_fit_search_selection_or_generation_call():
    tree = ast.parse(SOURCE.read_text())
    forbidden = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = (
            node.func.attr
            if isinstance(node.func, ast.Attribute)
            else node.func.id
            if isinstance(node.func, ast.Name)
            else ""
        ).lower()
        if name.startswith(("fit", "candidate", "select", "generate")):
            forbidden.append(name)
    assert forbidden == []


def test_fixed_threshold_table_uses_only_declared_phase_13_cuts():
    frame = pd.DataFrame(
        {
            "device_id": ["a", "a", "b", "c"],
            "label": [1, 1, 0, 0],
        }
    )
    risk = np.array([0.2, 0.8, 0.4, 0.95])
    table = threshold_diagnostics(frame, risk)
    assert tuple(table.threshold) == FIXED_THRESHOLDS
    at_75 = table.loc[table.threshold.eq(0.75)].iloc[0]
    assert at_75.attack_devices_detected == 1
    assert at_75.legitimate_devices_flagged == 1


def test_detection_delay_and_wilson_helpers_are_count_transparent():
    devices = pd.DataFrame(
        {
            "label": [1, 1, 1],
            "scenario": ["patient"] * 3,
            "ever_reviewed": [True, True, False],
            "ever_blocked": [False, True, False],
            "first_review_attempt": [2.0, 3.0, np.nan],
            "first_block_attempt": [np.nan, 5.0, np.nan],
        }
    )
    result = detection_group(devices, ("patient",))
    assert result["reviewed_devices"] == 2
    assert result["blocked_devices"] == 1
    assert result["never_detected_devices"] == 1
    interval = wilson_interval(1, 3)
    assert 0 < interval["low"] < interval["high"] < 1


def test_result_hashes_bind_every_phase_13_artifact_when_evaluated():
    path = ROOT / "artifacts/evaluation/blind_v2_result_hashes.json"
    if not path.exists():
        return
    import hashlib

    manifest = json.loads(path.read_text())
    assert manifest["evaluated"] is True
    assert manifest["consumed"] is True
    for key, relative in manifest["files"].items():
        actual = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert actual == manifest["hashes"][key]
