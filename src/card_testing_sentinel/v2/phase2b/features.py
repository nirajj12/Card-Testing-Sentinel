"""Central Phase 2B causal and model feature contracts."""

import hashlib

from card_testing_sentinel.v2.modeling.features import (
    MODEL_FEATURE_COLUMNS as V2_MODEL_FEATURES,
)

NEW_FEATURES = (
    "prior_attempts_14d",
    "distinct_cards_14d",
    "amount_continuity_score_30d",
    "amount_continuity_history_available",
    "ip_rotation_ratio_24h",
    "checkout_completion_lag_seconds",
    "checkout_completion_lag_available",
)

MODEL_FEATURE_COLUMNS = (*V2_MODEL_FEATURES, *NEW_FEATURES)
MODEL_FEATURE_COLUMNS_SHA256 = hashlib.sha256(
    "\n".join(MODEL_FEATURE_COLUMNS).encode()
).hexdigest()

FORBIDDEN_MODEL_TERMS = (
    "label",
    "population",
    "attack_subtype",
    "scenario_tag",
    "split",
    "result",
    "outcome",
    "device_id",
    "session_id",
    "fingerprint",
    "card_token",
)


def validate_model_feature_contract() -> None:
    """Fail closed if the explicit ordered allowlist becomes unsafe."""
    if len(MODEL_FEATURE_COLUMNS) != len(set(MODEL_FEATURE_COLUMNS)):
        raise ValueError("Phase 2B model features must be unique")
    leaked = [
        name
        for name in MODEL_FEATURE_COLUMNS
        if any(term in name for term in FORBIDDEN_MODEL_TERMS)
    ]
    if leaked:
        raise ValueError(f"unsafe Phase 2B model features: {leaked}")
