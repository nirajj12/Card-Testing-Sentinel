import pandas as pd

from card_testing_sentinel.evaluation.sequential import (
    device_summary,
    sequential_metrics,
)


def _replay():
    return pd.DataFrame(
        {
            "device_id": ["attack-1", "attack-1", "attack-never", "legit"],
            "timestamp": pd.to_datetime(
                ["2026-01-01", "2026-01-02", "2026-01-01", "2026-01-01"]
            ),
            "population": ["attack", "attack", "attack", "normal"],
            "attack_subtype": ["burst", "burst", "patient", pd.NA],
            "scenario_tag": [
                "attack_burst",
                "attack_burst",
                "attack_patient",
                "normal_standard",
            ],
            "true_label": [1, 1, 1, 0],
            "authorization_position": [1, 2, 1, 1],
            "card_token": ["c1", "c2", "c3", "c4"],
            "action": [
                "block_next_attempt",
                "potentially_prevented",
                "allow",
                "review",
            ],
            "potentially_prevented": [False, True, False, False],
        }
    )


def test_first_attempt_and_never_detected_denominators():
    replay = _replay()
    summary = device_summary(replay)
    metrics = sequential_metrics(summary, replay, [1, 3])
    detected = summary.loc[summary["device_id"].eq("attack-1")].iloc[0]
    assert detected["attempts_before_detection"] == 0
    assert detected["attempts_processed_through_detection"] == 1
    assert detected["distinct_cards_before_detection_attempt"] == 0
    assert detected["distinct_cards_processed_through_detection"] == 1
    assert metrics["detected_within_attempt"]["1"]["denominator_devices"] == 2
    assert metrics["never_detected_attacker_devices"] == 1
    assert metrics["replay_estimated_potentially_preventable_attempts"] == 1
