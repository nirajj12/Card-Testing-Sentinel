"""Gate 7 (corrective pass, coverage raise): direct behavioral unit tests for
the frozen policy candidate-selection logic in
src/card_testing_sentinel/v2/policy/selection.py. Every function here is a
pure function over dicts/floats/ints -- no I/O, no synthetic dataset needed.
These tests assert on the actual documented decision semantics (allow/
review/block thresholds, tie-skip behavior, deterministic tie-break field
order), not on incidental values.
"""

import math

from card_testing_sentinel.v2.policy.selection import (
    choose_action,
    comparison_tuple,
    conservative_threshold_score,
    enumerate_policy_grid,
    policy_complexity,
)

# ---------------------------------------------------------------------------
# enumerate_policy_grid
# ---------------------------------------------------------------------------

_CONFIG = {
    "families": {
        "rules_only": {"review_scores": [2, 4], "block_scores": [3, 4]},
        "ml_only": {"review_thresholds": [0.2, 0.9], "block_thresholds": [0.5, 0.9]},
        "combined": {
            "review_thresholds": [0.3],
            "block_thresholds": [0.7],
            "review_scores": [2, 3],
            "block_support_scores": [2, 3],
        },
    }
}


def test_enumerate_policy_grid_skips_rules_only_pairs_where_review_not_below_block():
    candidates = enumerate_policy_grid(_CONFIG)
    rules_only = [c for c in candidates if c["family"] == "rules_only"]
    # (2,3), (2,4), (4,4)->skipped(review>=block), (4,3)->skipped
    assert {(c["review_score"], c["block_score"]) for c in rules_only} == {
        (2, 3),
        (2, 4),
    }


def test_enumerate_policy_grid_skips_ml_only_pairs_where_review_not_below_block():
    candidates = enumerate_policy_grid(_CONFIG)
    ml_only = [c for c in candidates if c["family"] == "ml_only"]
    # (0.2,0.5), (0.2,0.9) kept; (0.9,0.5) skipped; (0.9,0.9) skipped (review>=block)
    assert {(c["review_threshold"], c["block_threshold"]) for c in ml_only} == {
        (0.2, 0.5),
        (0.2, 0.9),
    }


def test_enumerate_policy_grid_skips_combined_when_review_score_not_below_support():
    candidates = enumerate_policy_grid(_CONFIG)
    combined = [c for c in candidates if c["family"] == "combined"]
    # review=0.3 < block=0.7 always true here; review_score/support pairs:
    # (2,2)->skip (not <), (2,3)->kept, (3,2)->skip (2<3 false since 3>=2), (3,3)->skip
    assert {(c["review_score"], c["block_support_score"]) for c in combined} == {(2, 3)}


def test_enumerate_policy_grid_candidate_ids_are_sequential_and_deterministic():
    candidates = enumerate_policy_grid(_CONFIG)
    ids = [c["candidate_id"] for c in candidates]
    assert ids == [f"policy_{i:03d}" for i in range(len(candidates))]
    # Running again from the identical config produces an identical grid.
    assert enumerate_policy_grid(_CONFIG) == candidates


def test_enumerate_policy_grid_empty_family_grids_produce_no_candidates():
    empty_config = {
        "families": {
            "rules_only": {"review_scores": [], "block_scores": []},
            "ml_only": {"review_thresholds": [], "block_thresholds": []},
            "combined": {
                "review_thresholds": [],
                "block_thresholds": [],
                "review_scores": [],
                "block_support_scores": [],
            },
        }
    }
    assert enumerate_policy_grid(empty_config) == []


# ---------------------------------------------------------------------------
# choose_action -- every branch of every family.
# ---------------------------------------------------------------------------


def test_choose_action_rules_only_all_three_outcomes():
    candidate = {"family": "rules_only", "review_score": 2, "block_score": 4}
    assert choose_action(candidate, probability=0.99, rule_score=1) == "allow"
    assert choose_action(candidate, probability=0.0, rule_score=2) == "review"
    assert (
        choose_action(candidate, probability=0.0, rule_score=4)
        == "block_current_attempt"
    )


def test_choose_action_ml_only_all_three_outcomes():
    candidate = {"family": "ml_only", "review_threshold": 0.2, "block_threshold": 0.8}
    assert choose_action(candidate, probability=0.1, rule_score=99) == "allow"
    assert choose_action(candidate, probability=0.2, rule_score=99) == "review"
    assert (
        choose_action(candidate, probability=0.8, rule_score=99)
        == "block_current_attempt"
    )


def test_choose_action_combined_requires_both_signals_to_block():
    candidate = {
        "family": "combined",
        "review_threshold": 0.3,
        "block_threshold": 0.7,
        "review_score": 2,
        "block_support_score": 3,
    }
    # High probability alone, without rule support, is only a review.
    assert choose_action(candidate, probability=0.9, rule_score=0) == "review"
    # High rule score alone, without probability over block threshold, is only a review.
    assert choose_action(candidate, probability=0.0, rule_score=3) == "review"
    # Both signals over their block thresholds -> block.
    assert (
        choose_action(candidate, probability=0.9, rule_score=3)
        == "block_current_attempt"
    )
    # Neither signal reaches review -> allow.
    assert choose_action(candidate, probability=0.0, rule_score=0) == "allow"
    # Only the rule review_score alone (below combined's block-support) reviews.
    assert choose_action(candidate, probability=0.0, rule_score=2) == "review"


# ---------------------------------------------------------------------------
# policy_complexity / conservative_threshold_score
# ---------------------------------------------------------------------------


def test_policy_complexity_orders_families_from_simplest_to_most_complex():
    assert policy_complexity({"family": "rules_only"}) == 0
    assert policy_complexity({"family": "ml_only"}) == 1
    assert policy_complexity({"family": "combined"}) == 2


def test_conservative_threshold_score_sums_only_threshold_and_score_fields():
    candidate = {
        "candidate_id": "policy_000",
        "family": "combined",
        "review_threshold": 0.3,
        "block_threshold": 0.7,
        "review_score": 2,
        "block_support_score": 3,
    }
    # candidate_id/family must be excluded; only *threshold*/*score* keys count.
    assert conservative_threshold_score(candidate) == 0.3 + 0.7 + 2 + 3


def test_conservative_threshold_score_ignores_non_numeric_metadata_fields():
    candidate = {
        "candidate_id": "policy_001",
        "family": "rules_only",
        "review_score": 2,
        "block_score": 4,
    }
    assert conservative_threshold_score(candidate) == 6.0


# ---------------------------------------------------------------------------
# comparison_tuple -- deterministic tie-break ordering.
# ---------------------------------------------------------------------------

_BASE_METRICS = {
    "worst_subtype_review_coverage": 0.5,
    "macro_subtype_review_coverage": 0.6,
    "worst_subtype_block_coverage": 0.3,
    "macro_subtype_block_coverage": 0.4,
    "median_processed_authorizations_before_first_action": 2.0,
    "legitimate_blocks": 1,
    "legitimate_review_or_higher": 5,
}


def test_comparison_tuple_field_order_matches_selection_objective():
    candidate = {
        "candidate_id": "policy_000",
        "family": "rules_only",
        "review_score": 2,
        "block_score": 4,
    }
    tup = comparison_tuple(_BASE_METRICS, candidate)
    assert tup[0] == 0.5  # worst_subtype_review_coverage
    assert tup[1] == 0.6  # macro_subtype_review_coverage
    assert tup[2] == 0.3  # worst_subtype_block_coverage
    assert tup[3] == 0.4  # macro_subtype_block_coverage
    assert tup[4] == -2.0  # negated delay (lower delay is better -> higher tuple)
    assert tup[5] == -1  # negated legitimate_blocks (fewer is better)
    assert tup[6] == -5  # negated legitimate_review_or_higher (fewer is better)
    assert tup[7] == -0  # negated complexity for rules_only (0)
    assert tup[8] == 6.0  # conservative_threshold_score
    expected_json = (
        '{"block_score": 4, "candidate_id": "policy_000", '
        '"family": "rules_only", "review_score": 2}'
    )
    assert tup[9] == expected_json


def test_comparison_tuple_treats_nan_delay_as_a_very_large_penalty():
    metrics = dict(_BASE_METRICS)
    metrics["median_processed_authorizations_before_first_action"] = math.nan
    candidate = {
        "candidate_id": "policy_000",
        "family": "ml_only",
        "review_threshold": 0.2,
        "block_threshold": 0.8,
    }
    tup = comparison_tuple(metrics, candidate)
    assert tup[4] == -1e12


def test_comparison_tuple_is_a_total_order_breaking_every_tie_by_json_candidate():
    # Two candidates with identical metrics differ only by their serialized
    # JSON -- the final tuple field must make the ordering deterministic
    # rather than arbitrary/unstable.
    metrics = dict(_BASE_METRICS)
    candidate_a = {
        "candidate_id": "policy_000",
        "family": "rules_only",
        "review_score": 2,
        "block_score": 4,
    }
    candidate_b = {
        "candidate_id": "policy_001",
        "family": "rules_only",
        "review_score": 2,
        "block_score": 4,
    }
    tup_a = comparison_tuple(metrics, candidate_a)
    tup_b = comparison_tuple(metrics, candidate_b)
    assert tup_a[:9] == tup_b[:9]
    assert tup_a[9] != tup_b[9]
    # Sorting is therefore stable/deterministic regardless of input order.
    assert sorted([tup_b, tup_a]) == sorted([tup_a, tup_b])


def test_comparison_tuple_prefers_lower_complexity_when_everything_else_ties():
    metrics = dict(_BASE_METRICS)
    simple = {
        "candidate_id": "policy_000",
        "family": "rules_only",
        "review_score": 2,
        "block_score": 4,
    }
    complex_ = {
        "candidate_id": "policy_001",
        "family": "combined",
        "review_threshold": 0.0,
        "block_threshold": 0.0,
        "review_score": 2,
        "block_support_score": 4,
    }
    tup_simple = comparison_tuple(metrics, simple)
    tup_complex = comparison_tuple(metrics, complex_)
    # Simpler family (lower complexity) has a *higher* (less negative) tuple
    # value at that position, so max() on the objective favors it when tied.
    assert tup_simple[7] > tup_complex[7]
