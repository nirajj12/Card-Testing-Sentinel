import inspect
import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import joblib
import numpy as np
import pandas as pd
import pytest

from card_testing_sentinel.v2.phase2b.validation_policy import OptimizedFrozenScorer
from card_testing_sentinel.v2.phase2c.replay import (
    candidate_metrics,
    integer_budgets,
    replay_stateful_candidate,
)
from card_testing_sentinel.v2.phase3.contracts import (
    EFFECTIVENESS_TARGETS,
    SAFETY_ALLOWANCES,
)
from card_testing_sentinel.v2.phase3.evaluation import (
    TimedScorer,
    result_status,
    run_blind_once,
)
from card_testing_sentinel.v2.phase3.lifecycle import (
    generate_blind_frames,
    sha256_file,
)


def _devices() -> pd.DataFrame:
    rows = []
    counts = {
        "normal_standard": (1200, 0, None),
        "normal_bad_luck": (100, 0, None),
        "flash_standard": (300, 0, None),
        "flash_hard_retry": (100, 0, None),
        "attack_burst": (120, 1, "burst"),
        "attack_evasive": (90, 1, "evasive"),
        "attack_patient": (90, 1, "patient"),
    }
    index = 0
    for scenario, (count, label, subtype) in counts.items():
        for _ in range(count):
            index += 1
            rows.append(
                {
                    "device_id": f"d{index}",
                    "label": label,
                    "population": "attack" if label else "normal",
                    "attack_subtype": subtype,
                    "scenario_tag": scenario,
                    "review_or_higher": bool(label),
                    "blocked": bool(label),
                    "first_review_or_higher_request": 4 if label else np.nan,
                    "first_block_request": 5 if label else np.nan,
                    "requests_scored_through_first_action": 4,
                    "authorizations_processed_before_first_action": 3,
                    "distinct_cards_requested_through_first_action": 2,
                    "distinct_cards_processed_before_first_action": 2,
                    "seconds_to_first_review": 30 if label else np.nan,
                    "potentially_preventable_later_requests_upper_bound": 0,
                }
            )
    return pd.DataFrame(rows)


def test_integer_safety_allowances_and_full_attacker_denominators():
    devices = _devices()
    rates = {
        "overall_legitimate": {"review_or_higher_rate": 0.03, "block_rate": 0.01},
        "normal_standard": {"review_or_higher_rate": 0.02, "block_rate": 0.005},
        "normal_bad_luck": {"review_or_higher_rate": 0.05, "block_rate": 0.02},
        "flash_standard": {"review_or_higher_rate": 0.05, "block_rate": 0.03},
        "flash_hard_retry": {"review_or_higher_rate": 0.10, "block_rate": 0.05},
    }
    budgets = integer_budgets(devices, rates)
    assert {
        name: {
            "review_or_higher": row["review_or_higher_allowance"],
            "block": row["block_allowance"],
        }
        for name, row in budgets.items()
    } == SAFETY_ALLOWANCES
    metrics = candidate_metrics(devices, rates, EFFECTIVENESS_TARGETS)
    assert metrics["attacker_review_or_higher"]["denominator"] == 300
    assert all(
        row["review_or_higher"]["denominator"] in {90, 120}
        for row in metrics["subtype"].values()
    )
    assert result_status(metrics) == "blind_completed_passed"


def test_failed_constraints_assign_honest_status():
    metrics = {"safety_passed": False, "effectiveness_passed": True}
    assert result_status(metrics) == "blind_completed_failed"
    assert result_status(metrics, integrity_passed=False) == "blind_execution_failed"


def test_timed_scorer_uses_snapshot_without_dataframe():
    class Frozen:
        def score_snapshot(self, snapshot):
            assert isinstance(snapshot, dict)
            return 0.2, 0.3

    scorer = TimedScorer(Frozen())
    assert scorer.score_snapshot({"feature": 1}) == (0.2, 0.3)
    assert len(scorer.latencies_ns) == 1


def _event(event_id, request_id, sequence, timestamp, event_type, **extra):
    base = {
        "event_id": event_id,
        "request_id": request_id,
        "event_sequence": sequence,
        "timestamp": timestamp.isoformat(),
        "event_type": event_type,
        "device_id": "d1",
        "session_id": "s1",
        "population": "attack",
        "attack_subtype": "burst",
        "scenario_tag": "attack_burst",
        "label": 1,
        "ip_fingerprint": None,
        "card_fingerprint": None,
        "card_bin": None,
        "amount": None,
        "currency": None,
        "campaign_active": None,
        "authorization_result": None,
        "decline_reason": None,
    }
    base.update(extra)
    return base


def test_post_block_request_is_still_scored_without_outcome_leakage():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    rows = []
    for index in range(1, 7):
        request_time = start + timedelta(seconds=index * 10)
        request_id = f"r{index}"
        rows.append(
            _event(
                f"q{index}",
                request_id,
                index * 2 - 1,
                request_time,
                "authorization_request",
                ip_fingerprint="ip1",
                card_fingerprint=f"c{index}",
                card_bin="410000",
                amount=2.0,
                currency="USD",
                campaign_active=False,
            )
        )
        rows.append(
            _event(
                f"o{index}",
                request_id,
                index * 2,
                request_time + timedelta(seconds=1),
                "authorization_outcome",
                authorization_result="declined",
                decline_reason="generic_decline",
            )
        )
    raw = pd.DataFrame(rows)
    contract = pd.DataFrame(
        [
            {
                "device_id": "d1",
                "label": 1,
                "population": "attack",
                "attack_subtype": "burst",
                "scenario_tag": "attack_burst",
            }
        ]
    )

    class Scorer:
        def score_snapshot(self, snapshot):
            assert "authorization_result" not in snapshot
            return 0.9, 0.9

    candidate = {
        "candidate_id": "phase2c_002",
        "family": "persistent_ml",
        "review_rule_score": 99,
        "block_rule_score": 99,
        "high_window_hours": 336,
        "half_life_hours": 168,
        "recent_request_limit": 16,
        "strong_threshold": 0.8,
        "checkout_risk_multiplier": 0.55,
        "stable_retry_risk_multiplier": 0.8,
        "campaign_threshold_increment": 0.0,
        "campaign_extra_evidence": 0,
        "review_threshold": 0.5,
        "review_high_count": 3,
        "block_threshold": 0.6,
        "block_high_count": 4,
        "block_evidence": 0,
    }
    decisions, devices, audit = replay_stateful_candidate(
        raw, contract, Scorer(), candidate, capture_decisions=True
    )
    assert len(decisions) == 6
    assert decisions.iloc[3].action == "block"
    assert decisions.iloc[4].action == "block"
    assert "counterfactual_after_block" not in set(decisions.action)
    assert audit["requests_scored"] == 6
    assert audit["blocked_outcomes_suppressed"] == 3
    assert devices.iloc[0].potentially_preventable_later_requests_upper_bound == 2


def test_exactly_one_policy_contract_has_no_grid():
    frozen = SimpleNamespace(candidate_id="phase2c_002", evaluated_policies=1)
    assert frozen.candidate_id == "phase2c_002"
    assert frozen.evaluated_policies == 1
    source = inspect.getsource(run_blind_once)
    assert "enumerate_candidates" not in source
    assert "candidate_grid" not in source


def test_frozen_model_and_calibrator_optimized_parity():
    artifact = joblib.load("artifacts/v2/phase2b/training/models/selected_model.joblib")
    fixture = pd.read_csv(
        "artifacts/v2/phase2b/training/models/serialization_fixture.csv"
    )
    report = OptimizedFrozenScorer(artifact).verify_parity(fixture, 1e-12)
    assert report["passed"]


def test_complete_tmp_blind_workflow_and_second_run_refusal(tmp_path, monkeypatch):
    config = {
        "seed": 20260828,
        "start_timestamp": "2026-07-01T00:00:00+00:00",
        "currency": "USD",
        "validation_fraction": 0.0,
        "device_counts": {
            "normal_standard": 1,
            "normal_bad_luck": 1,
            "flash_standard": 1,
            "flash_hard_retry": 1,
            "attack_burst": 1,
            "attack_evasive": 1,
            "attack_patient": 1,
        },
        "identifier_namespace": "fixture_blind",
        "parity_tolerance": 1e-12,
        "safety_rates": {
            "overall_legitimate": {
                "review_or_higher_rate": 1.0,
                "block_rate": 1.0,
            },
            "normal_standard": {"review_or_higher_rate": 1.0, "block_rate": 1.0},
            "normal_bad_luck": {"review_or_higher_rate": 1.0, "block_rate": 1.0},
            "flash_standard": {"review_or_higher_rate": 1.0, "block_rate": 1.0},
            "flash_hard_retry": {
                "review_or_higher_rate": 1.0,
                "block_rate": 1.0,
            },
        },
        "effectiveness_targets": {
            "overall_review_or_higher": 0.0,
            "overall_block": 0.0,
            "burst_review_or_higher": 0.0,
            "evasive_review_or_higher": 0.0,
            "patient_review_or_higher": 0.0,
        },
    }
    raw, contract = generate_blind_frames(config)
    data = tmp_path / "data/v2/phase3/blind"
    artifacts = tmp_path / "artifacts/v2/phase3/blind"
    data.mkdir(parents=True)
    artifacts.mkdir(parents=True)
    raw.to_csv(data / "raw_events.csv", index=False, float_format="%.6f")
    contract.to_csv(data / "device_contract.csv", index=False, float_format="%.6f")
    freeze = artifacts / "pre_access_freeze.json"
    freeze.write_text("{}\n")
    freeze.with_suffix(".sha256").write_text(sha256_file(freeze) + "\n")
    manifest = {
        "seed": 20260828,
        "generation_count": 1,
        "accepted": True,
        "pre_access_freeze_sha256": sha256_file(freeze),
        "files": {
            "raw_events.csv": sha256_file(data / "raw_events.csv"),
            "device_contract.csv": sha256_file(data / "device_contract.csv"),
        },
        "structural_validation": {
            "status": "passed",
            "seed": 20260828,
        },
        "determinism_evidence": {"real_dataset_generations": 1},
        "generation_runtime": {
            "dataset_generation_seconds": 0.01,
            "dataset_validation_seconds": 0.01,
        },
    }
    (data / "manifest.json").write_text(json.dumps(manifest, sort_keys=True))
    shutil.copy2(data / "manifest.json", artifacts / "dataset_manifest.json")
    ledger = {
        "version": "fixture",
        "current_state": "post_generation_pre_scoring",
        "accepted_scoring_attempts": 0,
        "transitions": [
            {"state": "pre_generation"},
            {"state": "post_generation_pre_scoring"},
        ],
        "scoring_access": [],
    }
    (artifacts / "access_ledger.json").write_text(json.dumps(ledger))
    for relative in (
        "artifacts/v2/phase2b/training/models/selected_model.joblib",
        "artifacts/v2/phase2c/confirmation/frozen_operational_policy.json",
    ):
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(Path(relative), destination)
    monkeypatch.setattr(
        "card_testing_sentinel.v2.phase3.evaluation.verify_pre_access_freeze",
        lambda _root: {},
    )
    monkeypatch.setattr(
        "card_testing_sentinel.v2.phase3.lifecycle.verify_pre_access_freeze",
        lambda _root: {},
    )
    monkeypatch.setattr(
        "card_testing_sentinel.v2.phase3.evaluation.load_blind_config",
        lambda _root: config,
    )
    result = run_blind_once(tmp_path)
    assert result["status"] == "blind_completed_passed"
    assert (artifacts / "final_hash_manifest.json").is_file()
    with pytest.raises(PermissionError, match="second blind"):
        run_blind_once(tmp_path)
