import hashlib

from card_testing_sentinel.v2.features.spec import MODEL_FEATURES

REMOVED_MODEL_FEATURES = {
    "prior_attempts_10s": (
        "Training-only correlation above 0.98 with prospective_requests_10s; "
        "the prospective feature is the operational precheck quantity."
    ),
    "prior_attempts_60s": (
        "Training-only correlation above 0.99 with prospective_requests_60s; "
        "retaining both adds no useful independent information."
    ),
}

MODEL_FEATURE_COLUMNS = tuple(
    name for name in MODEL_FEATURES if name not in REMOVED_MODEL_FEATURES
)
MODEL_FEATURE_COLUMNS_SHA256 = hashlib.sha256(
    "\n".join(MODEL_FEATURE_COLUMNS).encode()
).hexdigest()

