import numpy as np
import pandas as pd

from card_testing_sentinel.evaluation.metrics import (
    classification_metrics,
    subgroup_metrics,
)


def test_weighted_metrics_are_hand_verifiable():
    result = classification_metrics(
        np.array([0, 0, 1, 1]),
        np.array([0.1, 0.9, 0.8, 0.2]),
        0.5,
        np.ones(4),
    )
    assert result["precision"] == 0.5
    assert result["recall"] == 0.5
    assert result["false_positive_rate"] == 0.5


def test_subgroup_metadata_filters_do_not_enter_scores():
    metadata = pd.DataFrame(
        {
            "population": ["normal", "flash_sale", "attack"],
            "scenario_tag": ["normal_bad_luck", "flash_hard_retry", "attack_burst"],
            "attack_subtype": [pd.NA, pd.NA, "burst"],
        },
        dtype="string",
    )
    result = subgroup_metrics(
        metadata, pd.Series([0, 0, 1]), np.array([0.8, 0.1, 0.9]), 0.5, np.ones(3)
    )
    assert result["normal_bad_luck_false_positive_rate"] == 1.0
    assert result["flash_hard_retry_false_positive_rate"] == 0.0
    assert result["burst_row_recall"] == 1.0
