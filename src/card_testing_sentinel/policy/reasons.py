"""Stable, non-sensitive policy explanation contract.

Anything the policy emits must be in this tuple; an unlisted code fails
closed rather than reaching a caller.
"""

REASON_CODES = (
    # model / policy state
    "elevated_model_risk",
    "persistent_elevated_risk",
    "campaign_tolerance_applied",
    "degraded_rules_only",
    # corroborating evidence supporting a block
    "repeated_verified_failures",
    "verified_decline_streak",
    "multi_session_persistence",
    "ip_rotation_evidence",
    "sustained_request_burst",
    "rapid_retry_after_decline",
    # deterministic rule layer (degraded mode and audit)
    "rapid_request_velocity",
    "shared_ip_intensity",
    "low_amount_velocity",
    "historical_card_churn",
)
