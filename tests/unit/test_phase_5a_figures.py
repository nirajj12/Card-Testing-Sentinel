from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from scripts.generate_final_figures import (
    SOURCES,
    generate_final_figures,
    load_calibration,
    load_frozen_inputs,
)

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts/generate_final_figures.py"


def test_required_frozen_sources_exist():
    assert all((ROOT / relative).is_file() for relative in SOURCES.values())


def test_frozen_pbrss_values_are_read_from_family_and_delay_artifacts():
    data = load_frozen_inputs(ROOT)
    attack = {row["scenario"]: row for row in data["attack_scenarios"]}
    assert attack["stealth_low_amount_drip"]["review_plus_pct"] == 100
    assert attack["stealth_low_amount_drip"]["block_pct"] == 100
    assert attack["hybrid_credential_stuffing_probe"]["block_pct"] == 60.8
    assert attack["mixed_card_probe"]["review_plus_pct"] == 94
    assert attack["mixed_card_probe"]["block_pct"] == pytest.approx(44.9333333333)

    legitimate = {row["scenario"]: row for row in data["legitimate_scenarios"]}
    assert legitimate["charity_micro_donation_spike"]["review_plus_pct"] == 0
    assert legitimate["b2b_multi_corporate_card"][
        "review_plus_pct"
    ] == pytest.approx(7.2)
    assert legitimate["ordinary_checkout"]["review_plus_pct"] == 25.3
    delay = {row["attempt"]: row["surfaced_pct"] for row in data["detection_delay"]}
    assert delay == pytest.approx({1: 23.2, 2: 25.2, 3: 92.16, 5: 96.4})


def test_latency_and_economic_values_match_committed_artifacts():
    data = load_frozen_inputs(ROOT)
    latency_source = json.loads((ROOT / SOURCES["latency"]).read_text())
    economic_source = json.loads((ROOT / SOURCES["economics"]).read_text())
    assert data["latency"]["latency_ms"] == latency_source["latency_ms"]
    assert data["economics"]["scenarios"] == economic_source["scenarios"]
    assert data["latency"]["latency_ms"]["p50"] == pytest.approx(33.830896)
    assert (
        data["economics"]["scenarios"]["quiet_day"][
            "net_illustrative_value_inr"
        ]
        == -708_697.6
    )


def test_phase_4a_psi_values_are_loaded_and_ranked_from_csv():
    data = load_frozen_inputs(ROOT)
    shifts = data["feature_shift"]
    assert len(shifts) == 10
    assert shifts[0] == {
        "feature": "device_age_seconds",
        "psi": 6.853574024,
    }
    assert all(
        left["psi"] >= right["psi"]
        for left, right in zip(shifts, shifts[1:], strict=False)
    )


def test_missing_calibration_bins_safely_return_none(tmp_path):
    assert load_calibration(tmp_path / "missing.csv") is None
    incomplete = tmp_path / "incomplete.csv"
    incomplete.write_text("mean_predicted,observed_rate\n0.1,0.2\n")
    assert load_calibration(incomplete) is None


def test_all_figures_and_manifest_are_generated_from_frozen_sources(tmp_path):
    manifest = generate_final_figures(ROOT, tmp_path)
    expected = {
        "pbrss_scenario_performance.png",
        "pbrss_detection_delay.png",
        "pbrss_legitimate_friction.png",
        "pbrss_calibration.png",
        "phase_4a_feature_shift.png",
        "phase_4c_latency.png",
        "phase_4d_economic_scenarios.png",
    }
    assert {figure["filename"] for figure in manifest["figures"]} == expected
    assert manifest["skipped_figures"] == []
    assert manifest["generated_from_frozen_evidence"] is True
    assert manifest["model_rescored"] is False
    assert manifest["pbrss_rescored"] is False
    assert (tmp_path / "figure_manifest.json").is_file()
    for filename in expected:
        assert (tmp_path / filename).stat().st_size > 10_000
    for figure in manifest["figures"]:
        assert figure["generated_from_frozen_evidence"] is True
        assert figure["model_rescored"] is False
        assert figure["pbrss_rescored"] is False
        assert all(
            (ROOT / source["path"]).is_file()
            and len(source["sha256"]) == 64
            for source in figure["source_artifacts"]
        )


def test_missing_calibration_is_recorded_as_skip_without_rescoring(tmp_path):
    output_dir = tmp_path / "figures"
    manifest = generate_final_figures(
        ROOT,
        output_dir,
        calibration_override=tmp_path / "absent-calibration.csv",
    )
    assert not (output_dir / "pbrss_calibration.png").exists()
    assert manifest["skipped_figures"][0]["filename"] == "pbrss_calibration.png"
    assert "no rescoring attempted" in manifest["skipped_figures"][0]["reason"]


def test_script_has_no_model_runtime_or_scoring_imports_and_calls():
    tree = ast.parse(SCRIPT_PATH.read_text())
    imports = set()
    called_attributes = set()
    called_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            called_attributes.add(node.func.attr)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            called_names.add(node.func.id)
    forbidden_imports = (
        "card_testing_sentinel",
        "joblib",
        "sklearn",
    )
    forbidden_calls = {"score", "score_frame", "predict", "predict_proba"}
    assert not any(name.startswith(forbidden_imports) for name in imports)
    assert called_attributes.isdisjoint(forbidden_calls)
    assert called_names.isdisjoint(forbidden_calls)
