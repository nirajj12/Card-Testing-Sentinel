export type Decision = "allow" | "review" | "block";

export type SystemStatus = {
  ready: boolean;
  model_status: string;
  active_runtime_version?: string;
  model_version?: string;
  policy_version?: string;
  feature_count?: number;
  policy_stage?: string | null;
  database?: { type?: string; integrity?: string };
  razorpay?: { configured?: boolean; mode?: string };
};

export type PrecheckResponse = {
  request_id: string;
  event_id: string;
  decision: Decision;
  risk_score: number | null;
  rule_score: number;
  reason_codes: string[];
  decision_basis: string;
  model_status: string;
  device_state_version: number;
  latency_ms: number;
};

export type Operation = {
  decision: Decision;
  risk_score: number | null;
  risk_band?: string;
  reason_codes: string[];
  latency_ms?: number;
  evidence?: Record<string, number | string>;
  protected_reference?: string;
  state_version?: number;
};

export type ActivityAttempt = {
  id: string;
  attempt: number;
  amount: number;
  currency: string;
  timestamp?: string;
  requestId?: string;
  source: "razorpay_test" | "replay";
  operation: Operation;
  razorpay_order_created?: boolean;
  checkout_opened?: boolean;
  razorpay_payment_status?: string | null;
  signature_verified?: boolean;
  webhook_verified?: boolean;
  history_status?: string;
  payment_attempt_count?: number;
};

export type DurableActivity = {
  id: string;
  protected_reference: string;
  timestamp: string;
  amount: number;
  currency: string;
  source: "razorpay_test" | "replay";
  sentinel_decision: Decision;
  risk_score: number | null;
  reason_codes: string[];
  evidence: Record<string, number | string>;
  razorpay_order_created: boolean;
  checkout_opened: boolean;
  razorpay_payment_status: string | null;
  signature_verified: boolean;
  webhook_verified: boolean;
  history_status: string;
  payment_attempt_count: number;
};

export type RazorpayOrder = {
  sentinel_request_id: string;
  razorpay_order_id: string;
  key_id: string;
  amount: number;
  currency: string;
  test_mode: true;
  activity_id: string;
};

export type VerifiedPayment = {
  verified: true;
  sentinel_request_id: string;
  razorpay_order_id: string;
  razorpay_payment_id: string;
  payment_status: string;
  outcome_recorded: boolean;
  checkout_recorded: boolean;
  message: string;
};

export type BlindMetrics = {
  status: "available" | "unavailable";
  reason?: string;
  source: string;
  label: string;
  blind_version: string;
  active_runtime_version: string;
  model_version: string;
  policy_version: string;
  verdict: string;
  consumed: boolean;
  active_device_counts: { attack: number; legitimate: number };
  headline: {
    attack_intervention_rate: number;
    attack_block_rate: number;
    legitimate_intervention_rate: number;
    legitimate_block_rate: number;
  };
  model_metrics: { pr_auc: number; roc_auc: number; brier: number; ece: number };
  policy_metrics: {
    attack_review_or_higher_rate: number;
    attack_block_rate: number;
    legitimate_review_or_higher_rate: number;
    legitimate_block_rate: number;
  };
  operating_targets: Record<string, "PASS" | "FAIL">;
  detection_by_attempt: Record<string, number>;
  scenario_metrics: Array<{ scenario: string; population: "attack" | "legitimate"; devices: number; intervention_rate: number; block_rate: number }>;
  limitations: { hardest_attacks: string[]; highest_friction: string[]; summary: string };
  historical_evidence: { version: string; source: string; comparable_to_blind_v2: false };
  replay: { status: "not_packaged"; reason: string; missing_artifact: string };
  disclosure: string;
};

declare global {
  interface Window {
    Razorpay?: new (options: RazorpayOptions) => RazorpayInstance;
  }
}

export type RazorpayOptions = {
  key: string;
  amount: number;
  currency: string;
  name: string;
  description: string;
  order_id: string;
  prefill: { email: string; contact: string };
  theme: { color: string };
  handler: (payment: { razorpay_order_id: string; razorpay_payment_id: string; razorpay_signature: string }) => void | Promise<void>;
  modal: { ondismiss: () => void };
};

export type RazorpayInstance = { open: () => void; on: (event: string, callback: (response?: unknown) => void) => void };
