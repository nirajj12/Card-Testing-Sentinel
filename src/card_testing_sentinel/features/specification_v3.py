"""The ordered causal-feature contract, version 3.1.

v1 (28 features) and v2 (39 features) are untouched and continue to serve
their frozen artifacts. This module provides Feature Contract v3.1 (44 features).

Every feature is derivable from merchant-visible pre-checkout causality:
raw request facts, device historical requests, verified outcomes, and customer
history across devices.
No feature uses the current attempt's card, method, issuer, decline
reason or result, and none uses a future event.
"""

from __future__ import annotations

import hashlib

import yaml

from card_testing_sentinel.common.paths import project_root

_CONTRACT_PATH = project_root() / "configs/features_v3_1.yaml"
_CONTRACT = yaml.safe_load(_CONTRACT_PATH.read_text())

MODEL_FEATURES_V3: tuple[str, ...] = tuple(_CONTRACT["features"])
MODEL_FEATURES_V3_SHA256 = hashlib.sha256(
    "\n".join(MODEL_FEATURES_V3).encode()
).hexdigest()
FEATURE_CONTRACT_V3_VERSION = str(_CONTRACT["version"])

RETENTION = dict(_CONTRACT["retention"])
GAP_STATISTICS = dict(_CONTRACT["gap_statistics"])
CUSTOMER_MISSING_NEUTRAL = float(_CONTRACT["customer_missing_neutral"])

NEW_IN_V3 = (
    "card_diversity_ratio_7d",
    "card_change_after_decline_ratio_7d",
    "session_churn_rate_24h",
    "gap_coefficient_of_variation_24h",
    "median_inter_attempt_gap_seconds_24h",
)

CUSTOMER_FEATURES = (
    "customer_distinct_devices_7d",
    "customer_failures_7d",
    "customer_successful_checkouts_30d",
    "customer_age_seconds",
)

FORBIDDEN_TERMS = (
    "label",
    "population",
    "attack_subtype",
    "scenario",
    "split",
    "device_id",
    "session_id",
    "merchant_id",
    "customer_id",
    "fingerprint",
    "card_token",
    "card_reference",
    "card_bin",
    "pan",
    "cvv",
    "expiry",
    "authorization_result",
    "decline_reason",
)

FORBIDDEN_EXEMPT = ("customer_id_present",)


def validate_feature_contract_v3() -> None:
    if len(MODEL_FEATURES_V3) != len(set(MODEL_FEATURES_V3)):
        raise ValueError("feature contract v3 contains duplicates")
    if not MODEL_FEATURES_V3:
        raise ValueError("feature contract v3 is empty")
    unsafe = [
        name
        for name in MODEL_FEATURES_V3
        if name not in FORBIDDEN_EXEMPT
        and any(term in name for term in FORBIDDEN_TERMS)
    ]
    if unsafe:
        raise ValueError(f"unsafe feature names in v3: {unsafe}")


validate_feature_contract_v3()
