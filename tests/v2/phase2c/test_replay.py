from __future__ import annotations

import pandas as pd

from card_testing_sentinel.v2.phase2c.replay import replay_stateful_candidate


class _Scorer:
    def __init__(self):
        self.snapshots = []

    def score_snapshot(self, _snapshot):
        self.snapshots.append(dict(_snapshot))
        return 0.9, 0.9


class _SequenceScorer:
    def __init__(self, probabilities):
        self.probabilities = iter(probabilities)
        self.snapshots = []

    def score_snapshot(self, snapshot):
        self.snapshots.append(dict(snapshot))
        probability = next(self.probabilities)
        return probability, probability


def _candidate():
    return {
        "candidate_id": "fixture_001",
        "family": "persistent_ml",
        "review_rule_score": 99,
        "block_rule_score": 99,
        "high_window_hours": 336,
        "half_life_hours": 168,
        "recent_request_limit": 16,
        "strong_threshold": 0.8,
        "checkout_risk_multiplier": 0.5,
        "stable_retry_risk_multiplier": 0.8,
        "campaign_threshold_increment": 0,
        "campaign_extra_evidence": 0,
        "review_threshold": 0.5,
        "review_high_count": 1,
        "block_threshold": 0.7,
        "block_high_count": 1,
        "block_evidence": 0,
    }


def _raw():
    common = {
        "population": "normal",
        "attack_subtype": None,
        "scenario_tag": "normal_standard",
        "label": 0,
    }
    rows = [
        {
            "event_id": "e1",
            "request_id": "r1",
            "event_sequence": 1,
            "timestamp": "2026-01-01T00:00:00+00:00",
            "event_type": "authorization_request",
            "device_id": "d1",
            "session_id": "s1",
            "ip_fingerprint": "shared_ip",
            "card_fingerprint": "c1",
            "card_bin": "410000",
            "amount": 10.0,
            "currency": "USD",
            "campaign_active": False,
            "authorization_result": None,
            "decline_reason": None,
            **common,
        },
        {
            "event_id": "e2",
            "request_id": "r2",
            "event_sequence": 2,
            "timestamp": "2026-01-01T00:00:00+00:00",
            "event_type": "authorization_request",
            "device_id": "d2",
            "session_id": "s2",
            "ip_fingerprint": "shared_ip",
            "card_fingerprint": "c2",
            "card_bin": "410001",
            "amount": 11.0,
            "currency": "USD",
            "campaign_active": False,
            "authorization_result": None,
            "decline_reason": None,
            **common,
        },
        {
            "event_id": "e3",
            "request_id": "r1",
            "event_sequence": 3,
            "timestamp": "2026-01-01T00:00:01+00:00",
            "event_type": "authorization_outcome",
            "device_id": "d1",
            "session_id": "s1",
            "ip_fingerprint": None,
            "card_fingerprint": None,
            "card_bin": None,
            "amount": None,
            "currency": None,
            "campaign_active": None,
            "authorization_result": "approved",
            "decline_reason": None,
            **common,
        },
        {
            "event_id": "e4",
            "request_id": "r2",
            "event_sequence": 4,
            "timestamp": "2026-01-01T00:00:01+00:00",
            "event_type": "authorization_outcome",
            "device_id": "d2",
            "session_id": "s2",
            "ip_fingerprint": None,
            "card_fingerprint": None,
            "card_bin": None,
            "amount": None,
            "currency": None,
            "campaign_active": None,
            "authorization_result": "approved",
            "decline_reason": None,
            **common,
        },
        {
            "event_id": "e5",
            "request_id": "r1",
            "event_sequence": 5,
            "timestamp": "2026-01-01T00:01:00+00:00",
            "event_type": "checkout_completion",
            "device_id": "d1",
            "session_id": "s1",
            "ip_fingerprint": None,
            "card_fingerprint": None,
            "card_bin": None,
            "amount": None,
            "currency": None,
            "campaign_active": None,
            "authorization_result": None,
            "decline_reason": None,
            **common,
        },
    ]
    return pd.DataFrame(rows)


def test_block_suppresses_current_outcome_and_dependent_checkout_deterministically():
    raw = _raw()
    contract = raw.groupby("device_id", as_index=False).first()[
        ["device_id", "population", "attack_subtype", "scenario_tag", "label"]
    ]
    scorer = _Scorer()
    first = replay_stateful_candidate(
        raw, contract, scorer, _candidate(), capture_decisions=True
    )
    second = replay_stateful_candidate(
        raw, contract, _Scorer(), _candidate(), capture_decisions=True
    )
    decisions, devices, audit = first
    assert decisions.action.tolist() == ["block", "block"]
    assert devices.blocked.all()
    assert audit["blocked_outcomes_suppressed"] == 2
    assert audit["dependent_checkout_events_suppressed"] == 1
    assert scorer.snapshots[1]["requests_per_ip_5m"] == 2
    assert first[0].equals(second[0])
    assert first[1].equals(second[1])
    assert first[2] == second[2]


def _single_device_lifecycle():
    common = {
        "device_id": "device",
        "session_id": "session",
        "population": "normal",
        "attack_subtype": None,
        "scenario_tag": "normal_standard",
        "label": 0,
    }
    request_fields = {
        "ip_fingerprint": "shared_ip",
        "card_bin": "410000",
        "amount": 10.0,
        "currency": "USD",
        "campaign_active": False,
        "authorization_result": None,
        "decline_reason": None,
    }
    rows = []
    sequence = 0
    for index, outcome in enumerate(("declined", "approved", "approved"), start=1):
        sequence += 1
        rows.append(
            {
                "event_id": f"request_event_{index}",
                "request_id": f"request_{index}",
                "event_sequence": sequence,
                "timestamp": f"2026-01-01T00:00:0{index * 2 - 2}+00:00",
                "event_type": "authorization_request",
                "card_fingerprint": f"card_{index}",
                **request_fields,
                **common,
            }
        )
        sequence += 1
        rows.append(
            {
                "event_id": f"outcome_event_{index}",
                "request_id": f"request_{index}",
                "event_sequence": sequence,
                "timestamp": f"2026-01-01T00:00:0{index * 2 - 1}+00:00",
                "event_type": "authorization_outcome",
                "ip_fingerprint": None,
                "card_fingerprint": None,
                "card_bin": None,
                "amount": None,
                "currency": None,
                "campaign_active": None,
                "authorization_result": outcome,
                "decline_reason": "generic_decline" if outcome == "declined" else None,
                **common,
            }
        )
        if index == 2:
            sequence += 1
            rows.append(
                {
                    "event_id": "blocked_checkout",
                    "request_id": "request_2",
                    "event_sequence": sequence,
                    "timestamp": "2026-01-01T00:00:03.500000+00:00",
                    "event_type": "checkout_completion",
                    "ip_fingerprint": None,
                    "card_fingerprint": None,
                    "card_bin": None,
                    "amount": None,
                    "currency": None,
                    "campaign_active": None,
                    "authorization_result": None,
                    "decline_reason": None,
                    **common,
                }
            )
    return pd.DataFrame(rows).sort_values(
        ["timestamp", "event_sequence"], kind="mergesort"
    )


def test_allow_block_and_later_request_is_recomputed_without_outcome_leakage():
    raw = _single_device_lifecycle()
    contract = pd.DataFrame(
        [
            {
                "device_id": "device",
                "population": "normal",
                "attack_subtype": None,
                "scenario_tag": "normal_standard",
                "label": 0,
            }
        ]
    )
    scorer = _SequenceScorer([0.1, 0.9, 0.1])
    candidate = _candidate()
    candidate.update(
        {
            "family": "consecutive_high",
            "review_high_count": 1,
            "block_high_count": 1,
            "review_consecutive": 1,
            "block_consecutive": 1,
            "review_threshold": 0.5,
            "block_threshold": 0.7,
        }
    )
    decisions, devices, audit = replay_stateful_candidate(
        raw, contract, scorer, candidate, capture_decisions=True
    )
    assert decisions.action.tolist() == ["allow", "block", "allow"]
    assert len(scorer.snapshots) == 3
    later = scorer.snapshots[2]
    assert later["prospective_requests_60s"] == 3
    assert later["requests_per_ip_5m"] == 3
    assert later["sessions_7d"] == 1
    assert later["prior_attempts_24h"] == 1
    assert later["prior_decline_streak"] == 1
    assert later["prior_successful_checkouts"] == 0
    assert audit["blocked_outcomes_suppressed"] == 1
    assert audit["dependent_checkout_events_suppressed"] == 1
    assert audit["requests_scored"] == 3
    assert devices.iloc[0].potentially_preventable_later_requests_upper_bound == 1
    assert "counterfactual_after_block" not in set(decisions.action)


def test_multiple_current_request_blocks_do_not_stop_later_scoring():
    raw = _single_device_lifecycle()
    contract = pd.DataFrame(
        [
            {
                "device_id": "device",
                "population": "normal",
                "attack_subtype": None,
                "scenario_tag": "normal_standard",
                "label": 0,
            }
        ]
    )
    scorer = _SequenceScorer([0.9, 0.9, 0.6])
    candidate = _candidate()
    candidate.update(
        {
            "family": "consecutive_high",
            "review_high_count": 1,
            "block_high_count": 1,
            "review_consecutive": 1,
            "block_consecutive": 1,
            "review_threshold": 0.5,
            "block_threshold": 0.7,
        }
    )
    decisions, _devices, audit = replay_stateful_candidate(
        raw, contract, scorer, candidate, capture_decisions=True
    )
    assert decisions.action.tolist() == ["block", "block", "review"]
    assert audit["blocked_outcomes_suppressed"] == 2
    assert audit["requests_scored"] == 3
