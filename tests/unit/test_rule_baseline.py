from pathlib import Path

import pandas as pd
import yaml

from card_testing_sentinel.rules.baseline import score_rules

ROOT = Path(__file__).resolve().parents[2]


def test_rule_boundaries_scores_and_reason_codes():
    config = yaml.safe_load((ROOT / "configs/training.yaml").read_text())
    row = {
        "attempts_trailing_60s": 4,
        "unique_cards_trailing_60s": 3,
        "attempts_trailing_5min": 3,
        "decline_ratio_so_far": 0.67,
        "card_switch_rate": 0.67,
        "amount_near_minimum_ratio_5min": 0.50,
        "attempts_after_first_approval": 2,
        "unique_cards_trailing_5min": 3,
    }
    result = score_rules(pd.DataFrame([row]), config)
    assert result.loc[0, "rule_score"] == 5
    assert result.loc[0, "reason_codes"].split("|") == [
        "velocity_card_diversity",
        "repeated_declines",
        "rapid_card_switching",
        "near_minimum_probing",
        "continued_after_approval",
    ]
