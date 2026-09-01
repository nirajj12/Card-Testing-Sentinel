"""The ordered causal-feature contract.

Every feature is derivable from what a merchant knows when it calls Sentinel
(raw request facts + this device's own earlier requests + this device's
earlier *verified* payment outcomes). No feature uses the current attempt's
card, payment method, or outcome -- see ``configs/features.yaml``.
"""

from __future__ import annotations

import hashlib

import yaml

from card_testing_sentinel.common.paths import project_root

_CONTRACT = yaml.safe_load((project_root() / "configs/features.yaml").read_text())

MODEL_FEATURES: tuple[str, ...] = tuple(_CONTRACT["features"])
MODEL_FEATURES_SHA256 = hashlib.sha256("\n".join(MODEL_FEATURES).encode()).hexdigest()
FEATURE_CONTRACT_VERSION = str(_CONTRACT["version"])

# Substrings that must never appear in a feature name: labels, dataset
# bookkeeping, raw identifiers, and current-card / current-outcome fields.
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
    "authorization_result",
)


def validate_feature_contract() -> None:
    if len(MODEL_FEATURES) != len(set(MODEL_FEATURES)):
        raise ValueError("feature contract contains duplicates")
    if not MODEL_FEATURES:
        raise ValueError("feature contract is empty")
    unsafe = [
        name for name in MODEL_FEATURES if any(term in name for term in FORBIDDEN_TERMS)
    ]
    if unsafe:
        raise ValueError(f"unsafe feature names: {unsafe}")
