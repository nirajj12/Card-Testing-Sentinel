import numpy as np

from card_testing_sentinel.evaluation.thresholds import select_operating_point


def test_threshold_respects_budget_and_is_deterministic():
    y = np.array([0, 0, 1, 1])
    scores = np.array([0.1, 0.8, 0.7, 0.9])
    first = select_operating_point(y, scores, np.ones(4), 0.0)
    second = select_operating_point(y, scores, np.ones(4), 0.0)
    assert first == second
    assert first["feasible"] is True
    assert first["false_positive_rate"] == 0.0
    assert first["threshold"] == 0.9


def test_threshold_marks_no_nontrivial_point_infeasible():
    result = select_operating_point(
        np.array([0, 1]), np.array([1.0, 0.0]), np.ones(2), 0.0
    )
    assert result["feasible"] is False
