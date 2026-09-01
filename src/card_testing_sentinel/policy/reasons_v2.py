"""Policy v2 explanation contract.

Extends the v1 codes rather than replacing them: the deterministic rule layer
and the model-state codes are unchanged, so a v2 decision reads the same way
a v1 one did. Everything v2 adds is either a longer-horizon version of an
existing signal or an explicit statement that historical trust suppressed a
block.

Anything the policy emits must be in this tuple; an unlisted code fails
closed rather than reaching a caller.
"""

from card_testing_sentinel.policy.reasons import REASON_CODES

REASON_CODES_V2 = REASON_CODES + (
    # long-horizon corroboration (device)
    "sustained_failures_7d",
    "multi_day_activity_7d",
    "sustained_requests_7d",
    "irregular_cadence",
    # cross-device corroboration (customer). Never device-count alone.
    "account_failures_across_devices",
    "account_device_spread_with_failures",
    # historical trust, which withholds a block rather than granting one
    "established_account_history",
    "recent_successful_payments",
    "block_withheld_insufficient_evidence",
    "block_withheld_established_history",
)
