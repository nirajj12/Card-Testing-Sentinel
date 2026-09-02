import type { Operation, PrecheckResponse } from "../types";

export const policyV2ReasonCodes = [
  "elevated_model_risk",
  "persistent_elevated_risk",
  "campaign_tolerance_applied",
  "degraded_rules_only",
  "repeated_verified_failures",
  "verified_decline_streak",
  "multi_session_persistence",
  "ip_rotation_evidence",
  "sustained_request_burst",
  "rapid_retry_after_decline",
  "rapid_request_velocity",
  "shared_ip_intensity",
  "low_amount_velocity",
  "historical_card_churn",
  "sustained_failures_7d",
  "multi_day_activity_7d",
  "sustained_requests_7d",
  "irregular_cadence",
  "account_failures_across_devices",
  "account_device_spread_with_failures",
  "established_account_history",
  "recent_successful_payments",
  "block_withheld_insufficient_evidence",
  "block_withheld_established_history",
] as const;

export type PolicyV2ReasonCode = (typeof policyV2ReasonCodes)[number];
export type ReasonPresentation = { label: string; explanation: string };

export const reasonPresentations: Record<PolicyV2ReasonCode, ReasonPresentation> = {
  elevated_model_risk: {
    label: "Elevated behavioral risk",
    explanation: "The model found the recent behavior more unusual than the policy's review threshold.",
  },
  persistent_elevated_risk: {
    label: "Risk remained elevated",
    explanation: "Elevated model risk continued across recent attempts rather than appearing only once.",
  },
  campaign_tolerance_applied: {
    label: "Campaign tolerance applied",
    explanation: "The merchant marked a campaign period, so the policy required more risk before intervening.",
  },
  degraded_rules_only: {
    label: "Rules-only fallback active",
    explanation: "The model was unavailable, so this decision used the published behavioral rules only.",
  },
  repeated_verified_failures: {
    label: "Repeated verified failures",
    explanation: "Recent signed payment history contains multiple verified declines for this device.",
  },
  verified_decline_streak: {
    label: "Consecutive verified declines",
    explanation: "Several verified declines occurred consecutively in the recent behavioral history.",
  },
  multi_session_persistence: {
    label: "Activity across several sessions",
    explanation: "Attempts linked to this device continued across multiple recent sessions.",
  },
  ip_rotation_evidence: {
    label: "Recent IP changes",
    explanation: "The same device reference appeared from more than one IP in recent history.",
  },
  sustained_request_burst: {
    label: "Sustained request activity",
    explanation: "This device generated a concentrated run of recent payment requests.",
  },
  rapid_retry_after_decline: {
    label: "Fast retries after declines",
    explanation: "Verified declines were often followed quickly by another attempt.",
  },
  rapid_request_velocity: {
    label: "Rapid request velocity",
    explanation: "Several payment requests arrived within a short period from this device.",
  },
  shared_ip_intensity: {
    label: "High activity from one IP",
    explanation: "The observed IP reference was linked to an unusually concentrated set of recent requests.",
  },
  low_amount_velocity: {
    label: "Repeated low-value attempts",
    explanation: "Several near-minimum payment amounts were attempted in a short period.",
  },
  historical_card_churn: {
    label: "Card references changed repeatedly",
    explanation: "Prior verified outcomes for this device involved several protected card references.",
  },
  sustained_failures_7d: {
    label: "Failures continued across the week",
    explanation: "Repeated verified payment failures continued across the last seven days.",
  },
  multi_day_activity_7d: {
    label: "Activity continued across days",
    explanation: "Payment attempts linked to this device appeared on several days in the last week.",
  },
  sustained_requests_7d: {
    label: "Sustained weekly request activity",
    explanation: "The device accumulated repeated payment requests across the last seven days.",
  },
  irregular_cadence: {
    label: "Irregular attempt timing",
    explanation: "The gaps between recent attempts varied substantially, adding supporting behavioral context.",
  },
  account_failures_across_devices: {
    label: "Account failures across devices",
    explanation: "Failed attempts linked to this customer identifier appeared across multiple devices.",
  },
  account_device_spread_with_failures: {
    label: "Device spread with failures",
    explanation: "This customer identifier appeared on several devices and also had verified failures.",
  },
  established_account_history: {
    label: "Established account history",
    explanation: "Longer-lived customer history provided trust context and softened an automatic block to review.",
  },
  recent_successful_payments: {
    label: "Recent successful payment history",
    explanation: "Recent verified successful checkouts provided historical trust context for this decision.",
  },
  block_withheld_insufficient_evidence: {
    label: "Automatic block withheld",
    explanation: "Model risk was high, but recent behavior did not contain enough supporting evidence to block automatically.",
  },
  block_withheld_established_history: {
    label: "Block softened by established history",
    explanation: "Risk and supporting evidence were high, but established payment history softened the action to review.",
  },
};

export const evidenceLabels: Record<string, string> = {
  requests_5m: "Observed requests in 5 minutes",
  recent_failures_24h: "Recent verified failures",
  decline_streak: "Consecutive verified declines",
  sessions_24h: "Observed sessions in 24 hours",
  ip_changes_24h: "Observed IP changes in 24 hours",
  successful_checkouts_30d: "Historical successful checkouts in 30 days",
};

const unknownReason: ReasonPresentation = {
  label: "Additional policy signal",
  explanation: "No merchant-facing explanation is available for this uncontracted reason code.",
};

export function presentReason(code: string): ReasonPresentation {
  return reasonPresentations[code as PolicyV2ReasonCode] || unknownReason;
}

export function safeReason(code: string) {
  return presentReason(code).label;
}

export function normalizePrecheck(result: PrecheckResponse): Operation {
  const score = result.risk_score;
  const riskBand = score === null ? "unavailable" : score < .25 ? "low" : score < .5 ? "elevated" : score < .75 ? "high" : "very high";
  return { decision: result.decision, risk_score: score, risk_band: riskBand, reason_codes: result.reason_codes || [], latency_ms: result.latency_ms, state_version: result.device_state_version };
}

export const decisionCopy = {
  allow: {
    label: "ALLOW",
    title: "Razorpay order creation permitted",
    copy: "Sentinel found insufficient evidence to stop this attempt. Payment approval still happens later through Razorpay.",
  },
  review: {
    label: "REVIEW",
    title: "Attempt held before Razorpay",
    copy: "Risk is elevated, but evidence is insufficient for an automatic block. This prototype suppresses order creation and does not operate a manual-review or step-up flow.",
  },
  block: {
    label: "BLOCK",
    title: "This attempt stopped before Razorpay",
    copy: "This action applies only to the current attempt, which cannot create an order. Future attempts are independently evaluated.",
  },
} as const;
