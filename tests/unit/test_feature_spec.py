import pytest

from card_testing_sentinel.common.exceptions import DataValidationError
from card_testing_sentinel.features.spec import (
    GENERATION_EVALUATION_COLUMNS,
    IDENTIFIER_ORDER_COLUMNS,
    LABEL_COLUMN,
    MODEL_FEATURES,
    RAW_AUTHORIZATION_OUTCOME_COLUMNS,
    validate_feature_contract,
)

EXPECTED_FEATURES = (
    "attempts_trailing_10s",
    "attempts_trailing_60s",
    "attempts_trailing_5min",
    "mean_interarrival_s",
    "var_interarrival_s",
    "unique_cards_trailing_60s",
    "unique_cards_trailing_5min",
    "unique_bins_trailing_60s",
    "unique_bins_trailing_5min",
    "decline_ratio_so_far",
    "current_decline_streak",
    "approval_ratio_so_far",
    "attempts_before_first_approval",
    "amount_near_minimum_ratio_5min",
    "amount_variance_so_far",
    "repeated_amount_ratio",
    "unique_amount_ratio",
    "cards_this_session",
    "session_age_s",
    "attempts_this_session",
    "checkout_completed_so_far",
    "attempts_after_first_approval",
    "device_reuse_count",
    "card_switch_rate",
    "ip_session_count_trailing_5min",
    "ip_device_count_trailing_5min",
)


def test_feature_allowlist_is_exact_ordered_and_unique() -> None:
    assert MODEL_FEATURES == EXPECTED_FEATURES
    assert len(MODEL_FEATURES) == len(set(MODEL_FEATURES)) == 26


def test_feature_allowlist_is_disjoint_from_every_excluded_group() -> None:
    excluded = set(GENERATION_EVALUATION_COLUMNS)
    excluded.update(IDENTIFIER_ORDER_COLUMNS)
    excluded.update(RAW_AUTHORIZATION_OUTCOME_COLUMNS)
    excluded.add(LABEL_COLUMN)

    assert set(MODEL_FEATURES).isdisjoint(excluded)
    validate_feature_contract(MODEL_FEATURES)


def test_feature_contract_rejects_missing_enriched_feature() -> None:
    with pytest.raises(DataValidationError, match="missing features"):
        validate_feature_contract(MODEL_FEATURES[:-1])
