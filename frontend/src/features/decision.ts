import type { Operation, PrecheckResponse } from "../types";

export const reasonLabels: Record<string, string> = {
  elevated_model_risk: "Elevated behavioral risk",
  repeated_verified_failures: "Repeated verified failures",
  verified_decline_streak: "Verified decline streak",
  multi_session_persistence: "Multiple recent sessions",
  ip_rotation_evidence: "Recent IP changes",
  sustained_request_burst: "High recent request activity",
  rapid_retry_after_decline: "Rapid retries after declines",
  campaign_tolerance_applied: "Campaign tolerance applied",
  degraded_rules_only: "Rules-only fallback active",
};

export const evidenceLabels: Record<string, string> = {
  requests_5m: "Requests in 5 minutes",
  recent_failures_24h: "Previous verified failures",
  decline_streak: "Verified decline streak",
  sessions_24h: "Sessions in 24 hours",
  ip_changes_24h: "IP changes in 24 hours",
  successful_checkouts: "Successful checkouts",
};

export function safeReason(code: string) {
  return reasonLabels[code] || "Additional policy signal";
}

export function normalizePrecheck(result: PrecheckResponse): Operation {
  const score = result.risk_score;
  const riskBand = score === null ? "unavailable" : score < .25 ? "low" : score < .5 ? "elevated" : score < .75 ? "high" : "very high";
  return { decision: result.decision, risk_score: score, risk_band: riskBand, reason_codes: result.reason_codes || [], latency_ms: result.latency_ms, state_version: result.device_state_version };
}

export const decisionCopy = {
  allow: { label: "ALLOW", title: "Order creation permitted", copy: "Sentinel completed the pre-authorization check. This request may proceed to Razorpay." },
  review: { label: "REVIEW", title: "Merchant intervention recommended", copy: "No automatic review workflow is configured, so no Razorpay order is created." },
  block: { label: "TEMPORARY BLOCK", title: "Payment path stopped", copy: "The request ended before order creation. Checkout will not open." },
} as const;
