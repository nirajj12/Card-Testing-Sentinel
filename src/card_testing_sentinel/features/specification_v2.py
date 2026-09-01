"""The ordered causal-feature contract, version 2.

v1 (``features/specification.py``, 28 features) is untouched and still serves
the frozen Model v1 artifact. This module is a parallel contract: a different
file, a different version string and therefore a different hash, so a
39-feature vector can never reach the 28-feature model.

Every feature is derivable from what a merchant knows when it calls Sentinel:
the raw request facts, this device's own earlier requests and verified
outcomes, and -- new in v2 -- this customer's earlier behaviour across their
devices. No feature uses the current attempt's card, method, issuer, decline
reason or result, and none uses a future event.
"""

from __future__ import annotations

import hashlib

import yaml

from card_testing_sentinel.common.paths import project_root

_CONTRACT = yaml.safe_load((project_root() / "configs/features_v2.yaml").read_text())

MODEL_FEATURES_V2: tuple[str, ...] = tuple(_CONTRACT["features"])
MODEL_FEATURES_V2_SHA256 = hashlib.sha256(
    "\n".join(MODEL_FEATURES_V2).encode()
).hexdigest()
FEATURE_CONTRACT_V2_VERSION = str(_CONTRACT["version"])

RETENTION = dict(_CONTRACT["retention"])
GAP_STATISTICS = dict(_CONTRACT["gap_statistics"])
CUSTOMER_MISSING_NEUTRAL = float(_CONTRACT["customer_missing_neutral"])

#: Features that only exist in v2.
NEW_IN_V2 = (
    "requests_7d",
    "failures_7d",
    "active_day_count_7d",
    "failures_per_active_day_7d",
    "median_gap_between_attempts",
    "gap_variability",
    "customer_id_present",
    "customer_distinct_devices_7d",
    "customer_failures_7d",
    "customer_successful_checkouts_30d",
    "customer_age_seconds",
)

#: Customer-scoped features, which take `CUSTOMER_MISSING_NEUTRAL` when the
#: request carries no customer identity. `customer_id_present` is deliberately
#: NOT in this set -- it is the availability indicator itself.
CUSTOMER_FEATURES = (
    "customer_distinct_devices_7d",
    "customer_failures_7d",
    "customer_successful_checkouts_30d",
    "customer_age_seconds",
)

#: Same forbidden substrings as v1, plus the current-outcome fields.
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

#: `customer_id_present` is an availability flag, not the identifier, so it is
#: exempt from the `customer_id` substring rule.
FORBIDDEN_EXEMPT = ("customer_id_present",)


def validate_feature_contract_v2() -> None:
    if len(MODEL_FEATURES_V2) != len(set(MODEL_FEATURES_V2)):
        raise ValueError("feature contract v2 contains duplicates")
    if not MODEL_FEATURES_V2:
        raise ValueError("feature contract v2 is empty")
    unsafe = [
        name
        for name in MODEL_FEATURES_V2
        if name not in FORBIDDEN_EXEMPT
        and any(term in name for term in FORBIDDEN_TERMS)
    ]
    if unsafe:
        raise ValueError(f"unsafe feature names: {unsafe}")
    from card_testing_sentinel.features.specification import MODEL_FEATURES_SHA256

    if MODEL_FEATURES_V2_SHA256 == MODEL_FEATURES_SHA256:
        raise ValueError("v2 contract hash collides with v1")
