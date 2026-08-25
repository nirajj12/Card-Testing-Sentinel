"""Explicit and ordered model-feature contract for frozen dataset v4."""

from collections.abc import Collection

from card_testing_sentinel.common.exceptions import DataValidationError

MODEL_FEATURES = (
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

GENERATION_EVALUATION_COLUMNS = (
    "population",
    "attack_subtype",
    "scenario_tag",
    "entity_label",
)

IDENTIFIER_ORDER_COLUMNS = (
    "event_id",
    "event_sequence",
    "timestamp",
    "device_id",
    "session_id",
    "ip_hash",
    "event_type",
    "card_token",
    "card_bin",
)

RAW_AUTHORIZATION_OUTCOME_COLUMNS = ("amount", "declined", "decline_reason")
LABEL_COLUMN = "entity_label"
MODEL_ROW_EVENT_TYPE = "authorization"


def validate_feature_contract(enriched_columns: Collection[str] | None = None) -> None:
    """Fail if the immutable allowlist is duplicated, unsafe, or unavailable."""
    if len(MODEL_FEATURES) != 26 or len(set(MODEL_FEATURES)) != 26:
        raise DataValidationError(
            "model feature allowlist must contain 26 unique columns"
        )

    excluded = set(GENERATION_EVALUATION_COLUMNS)
    excluded.update(IDENTIFIER_ORDER_COLUMNS)
    excluded.update(RAW_AUTHORIZATION_OUTCOME_COLUMNS)
    excluded.add(LABEL_COLUMN)
    overlap = sorted(set(MODEL_FEATURES) & excluded)
    if overlap:
        raise DataValidationError(
            f"model feature allowlist contains excluded fields: {overlap}"
        )

    if enriched_columns is not None:
        missing = [name for name in MODEL_FEATURES if name not in enriched_columns]
        if missing:
            raise DataValidationError(
                f"enriched events are missing features: {missing}"
            )
