"""Stable, non-sensitive policy explanation contract."""

REASON_CODES = (
    "persistent_high_model_risk",
    "consecutive_high_model_risk",
    "accumulated_model_risk",
    "high_risk_with_card_switching",
    "cross_session_card_diversity",
    "high_risk_with_ip_rotation",
    "high_risk_with_card_diversity",
    "successful_checkout_risk_reduction",
    "stable_retry_risk_reduction",
    "campaign_threshold_adjustment",
    "rule_corroborated_review",
    "rule_corroborated_block",
)
