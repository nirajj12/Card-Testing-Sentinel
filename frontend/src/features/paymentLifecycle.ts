import type { PaymentPhase } from "../types";

const PAYMENT_STATUS_LABELS: Record<string, string> = {
  signature_verified: "Signature verified — awaiting payment status",
  authorized: "Authorized — awaiting capture",
  captured: "Captured",
  paid: "Paid",
  failed: "Verified failed payment",
  failed_unverified: "Unverified failure report",
};

export function paymentStatusLabel(status: string | null | undefined) {
  if (!status) return "No payment status";
  return PAYMENT_STATUS_LABELS[status] || status.replaceAll("_", " ");
}

export function historyStatusLabel(status: string | null | undefined) {
  return status ? status.replaceAll("_", " ") : "not recorded";
}

export function isAuthoritativePayment(
  paymentStatus: string | null | undefined,
  historyStatus: string | null | undefined,
) {
  return (
    ["captured", "paid", "failed"].includes(paymentStatus || "") &&
    Boolean(historyStatus?.startsWith("recorded"))
  );
}

export function phaseForPaymentStatus(
  paymentStatus: string | null | undefined,
  historyStatus: string | null | undefined,
): PaymentPhase | null {
  if (paymentStatus === "failed" && isAuthoritativePayment(paymentStatus, historyStatus)) {
    return "failure";
  }
  if (
    ["captured", "paid"].includes(paymentStatus || "") &&
    isAuthoritativePayment(paymentStatus, historyStatus)
  ) {
    return "payment_complete";
  }
  if (["signature_verified", "authorized"].includes(paymentStatus || "")) {
    return "awaiting_authoritative_status";
  }
  return null;
}
