import pandas as pd

from card_testing_sentinel.policy.selection import evaluate_policy


def test_synthetic_validation_policy_pipeline():
    events = pd.DataFrame(
        {
            "event_id": ["e1", "e2", "e3"],
            "device_id": ["attack", "attack", "normal"],
            "session_id": ["s1", "s1", "s2"],
            "timestamp": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-01"]),
            "event_sequence": [1, 2, 3],
            "population": ["attack", "attack", "normal"],
            "attack_subtype": ["burst", "burst", pd.NA],
            "scenario_tag": ["attack_burst", "attack_burst", "normal_standard"],
            "true_label": [1, 1, 0],
            "card_token": ["c1", "c2", "c3"],
            "risk_score": [0.9, 0.1, 0.1],
            "rule_score": [3, 0, 0],
        }
    )
    config = {
        "detection_within_attempt_cutoffs": [1, 3, 5, 10],
        "maximum_legitimate_device_review_or_higher_rate": 0.05,
        "maximum_legitimate_device_block_rate": 0.01,
        "subgroup_block_guardrails": {
            "flash_sale": 0.03,
            "flash_hard_retry": 0.15,
            "normal_bad_luck": 0.10,
        },
    }
    result = evaluate_policy(
        events,
        "ml_only",
        {"ml_review_threshold": 0.8, "ml_block_threshold": 0.9},
        config,
    )
    assert result["feasible"] is True
    assert result["metrics"]["attacker_block_coverage"]["rate"] == 1.0
    assert result["metrics"]["detected_within_attempt"]["1"]["rate"] == 1.0
