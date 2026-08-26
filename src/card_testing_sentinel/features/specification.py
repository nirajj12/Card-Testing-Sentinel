"""Authoritative ordered causal-feature contracts."""

from __future__ import annotations

import hashlib

import yaml

from card_testing_sentinel.common.paths import project_root

PROJECT_ROOT = project_root()

BASE_FEATURES = tuple(
    yaml.safe_load((PROJECT_ROOT / "configs/features.yaml").read_text())["features"]
)

REMOVED_CORRELATED_FEATURES = {
    "prior_attempts_10s",
    "prior_attempts_60s",
}

EXTENDED_FEATURES = (
    "prior_attempts_14d",
    "distinct_cards_14d",
    "amount_continuity_score_30d",
    "amount_continuity_history_available",
    "ip_rotation_ratio_24h",
    "checkout_completion_lag_seconds",
    "checkout_completion_lag_available",
)

MODEL_FEATURES = (
    tuple(name for name in BASE_FEATURES if name not in REMOVED_CORRELATED_FEATURES)
    + EXTENDED_FEATURES
)
MODEL_FEATURES_SHA256 = hashlib.sha256("\n".join(MODEL_FEATURES).encode()).hexdigest()

FORBIDDEN_TERMS = (
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


def validate_feature_contract() -> None:
    if len(MODEL_FEATURES) != 44 or len(MODEL_FEATURES) != len(set(MODEL_FEATURES)):
        raise ValueError("model feature contract must contain 44 unique features")
    unsafe = [
        name for name in MODEL_FEATURES if any(term in name for term in FORBIDDEN_TERMS)
    ]
    if unsafe:
        raise ValueError(f"unsafe model features: {unsafe}")
