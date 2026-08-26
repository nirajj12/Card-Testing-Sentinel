"""Pre-access tests for optimized scoring and causal policy replay."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest

from card_testing_sentinel.v2.data.contracts import (
    ConflictingDuplicateError,
    LateEventError,
    LifecycleEvent,
)
from card_testing_sentinel.v2.phase2b.engine import Phase2BFeatureEngine
from card_testing_sentinel.v2.phase2b.fresh_validation import generate_fresh_frames
from card_testing_sentinel.v2.phase2b.validation_policy import (
    OptimizedFrozenScorer,
    _candidate_row,
    allow_all_replay,
    benchmark_candidates,
    detailed_candidate_metrics,
    replay_candidate,
    static_model_diagnostics,
    verify_allow_all_parity,
)

ROOT = Path(__file__).resolve().parents[3]


def _config(count=2):
    return {
        "version": "fixture",
        "seed": 20260826,
        "start_timestamp": "2026-03-01T00:00:00+00:00",
        "currency": "USD",
        "validation_fraction": 0.0,
        "device_counts": {
            name: count
            for name in (
                "normal_standard",
                "normal_bad_luck",
                "flash_standard",
                "flash_hard_retry",
                "attack_burst",
                "attack_evasive",
                "attack_patient",
            )
        },
        "expected_counts": {"devices": 7 * count},
        "identifier_namespace": "policy_fixture",
    }


class RecordingScorer:
    def __init__(self, probability):
        self.probability = probability
        self.snapshots = []

    def score_snapshot(self, snapshot):
        self.snapshots.append(dict(snapshot))
        return self.probability, self.probability


def _ml_candidate(review, block):
    return {
        "candidate_id": "fixture",
        "family": "ml_only",
        "review_threshold": review,
        "block_threshold": block,
    }


def test_optimized_score_matches_serialized_artifact():
    raw, _ = generate_fresh_frames(_config())
    features = allow_all_replay(raw)
    artifact = joblib.load(
        ROOT / "artifacts/v2/phase2b/training/models/selected_model.joblib"
    )
    report = OptimizedFrozenScorer(artifact).verify_parity(features)
    assert report["maximum_absolute_difference"] <= 1e-12


def test_allow_all_online_batch_parity_uses_all_44_features():
    raw, _ = generate_fresh_frames(_config())
    features, report = verify_allow_all_parity(raw)
    assert report["feature_count"] == 44
    assert report["maximum_absolute_difference"] == 0
    assert len(features) == int(raw.event_type.eq("authorization_request").sum())


def test_allow_review_and_block_have_distinct_causal_state_semantics():
    raw, contract = generate_fresh_frames(_config(1))
    one_device = contract.iloc[[0]]
    device_raw = raw.loc[raw.device_id.eq(one_device.iloc[0].device_id)].copy()
    request_count = int(device_raw.event_type.eq("authorization_request").sum())

    allowing = RecordingScorer(0.0)
    decisions, _ = replay_candidate(
        device_raw,
        one_device,
        allowing,
        _ml_candidate(0.4, 0.9),
        capture_decisions=True,
    )
    assert set(decisions.action) == {"allow"}
    assert [row["prior_attempts_24h"] for row in allowing.snapshots] == list(
        range(request_count)
    )

    reviewing = RecordingScorer(0.5)
    decisions, devices = replay_candidate(
        device_raw,
        one_device,
        reviewing,
        _ml_candidate(0.4, 0.9),
        capture_decisions=True,
    )
    assert set(decisions.action) == {"review"}
    assert devices.iloc[0].review_or_higher
    assert not devices.iloc[0].blocked
    assert [row["prior_attempts_24h"] for row in reviewing.snapshots] == list(
        range(request_count)
    )

    blocking = RecordingScorer(1.0)
    decisions, devices = replay_candidate(
        device_raw,
        one_device,
        blocking,
        _ml_candidate(0.4, 0.9),
        capture_decisions=True,
    )
    assert len(blocking.snapshots) == 1
    assert devices.iloc[0].blocked
    assert devices.iloc[0].potentially_preventable_later_requests_upper_bound == (
        request_count - 1
    )
    assert int(decisions.action.eq("counterfactual_after_block").sum()) == (
        request_count - 1
    )


def test_engine_ties_duplicates_conflicts_and_late_events_fail_as_frozen():
    engine = Phase2BFeatureEngine()
    now = datetime(2026, 1, 1, tzinfo=UTC)
    request = LifecycleEvent(
        event_id="e1",
        request_id="r1",
        event_sequence=1,
        timestamp=now,
        event_type="authorization_request",
        device_id="d1",
        session_id="s1",
        ip_fingerprint="ip1",
        card_fingerprint="card1",
        card_bin="410000",
        amount=1.0,
        currency="USD",
        campaign_active=False,
    )
    first = engine.precheck(request)
    assert engine.precheck(request) == first
    with pytest.raises(ConflictingDuplicateError):
        engine.precheck(request.model_copy(update={"amount": 2.0}))
    tied = request.model_copy(
        update={"event_id": "e2", "request_id": "r2", "event_sequence": 2}
    )
    engine.precheck(tied)
    late = request.model_copy(
        update={
            "event_id": "e3",
            "request_id": "r3",
            "timestamp": now - timedelta(seconds=1),
        }
    )
    with pytest.raises(LateEventError):
        engine.precheck(late)


def test_all_78_candidates_are_replayed_once_in_frozen_order():
    raw, contract = generate_fresh_frames(_config(1))
    artifact = joblib.load(
        ROOT / "artifacts/v2/phase2b/training/models/selected_model.joblib"
    )
    scorer = OptimizedFrozenScorer(artifact)
    policy = json.loads(
        (
            ROOT / "artifacts/v2/phase2b/training/policy/policy_search_space.json"
        ).read_text()
    )
    benchmark = benchmark_candidates(raw, contract, scorer, policy["candidates"])
    assert benchmark["candidate_count"] == 78
    assert benchmark["candidate_requests"] == (benchmark["fixture_requests"] * 78)
    assert benchmark["one_row_dataframe_per_request"] is False


def test_metrics_keep_device_denominators_reviews_blocks_and_failure_excess_separate():
    devices = pd.DataFrame(
        {
            "device_id": ["l1", "a1", "a2", "a3"],
            "label": [0, 1, 1, 1],
            "scenario_tag": [
                "normal_standard",
                "attack_burst",
                "attack_evasive",
                "attack_patient",
            ],
            "attack_subtype": [None, "burst", "evasive", "patient"],
            "review_or_higher": [True, True, False, True],
            "blocked": [True, False, False, True],
            "first_review_or_higher_request": [1.0, 1.0, np.nan, 3.0],
            "first_block_request": [1.0, np.nan, np.nan, 3.0],
            "requests_scored_through_first_action": [1, 1, 4, 3],
            "authorizations_processed_before_first_action": [0, 0, 4, 2],
            "distinct_cards_requested_through_first_action": [1, 1, np.nan, 2],
            "distinct_cards_processed_before_first_action": [0, 0, np.nan, 1],
            "seconds_to_first_review": [0.0, 0.0, np.nan, 10.0],
            "potentially_preventable_later_requests_upper_bound": [1, 2, 0, 3],
        }
    )
    budget = {
        "overall_legitimate": {
            "review_or_higher_allowance": 0,
            "block_allowance": 0,
        },
        "normal_standard": {
            "review_or_higher_allowance": 0,
            "block_allowance": 0,
        },
    }
    metrics = detailed_candidate_metrics(devices, budget)
    assert not metrics["feasible"]
    assert metrics["budget_results"]["overall_legitimate"]["review_excess_devices"] == 1
    assert metrics["budget_results"]["overall_legitimate"]["block_excess_devices"] == 1
    assert metrics["within_attempt"]["10"]["denominator"] == 3
    assert metrics["never_detected_attackers"] == 1
    row = _candidate_row(_ml_candidate(0.4, 0.9), metrics)
    assert row["attacker_denominator_within_10_attempts"] == 3
    assert (
        "offline_upper_bound"
        in "potentially_preventable_later_attempts_offline_upper_bound"
    )


def test_static_reporting_is_deterministic_and_uses_only_frozen_thresholds():
    raw, _ = generate_fresh_frames(_config(1))
    features = allow_all_replay(raw)
    artifact = joblib.load(
        ROOT / "artifacts/v2/phase2b/training/models/selected_model.joblib"
    )
    scorer = OptimizedFrozenScorer(artifact)
    candidates = [_ml_candidate(0.4, 0.9)]
    first = static_model_diagnostics(features, scorer, candidates)
    second = static_model_diagnostics(features, scorer, candidates)
    assert first[0] == second[0]
    pd.testing.assert_frame_equal(first[1], second[1])
    assert set(first[2].threshold) == {0.4, 0.9}
