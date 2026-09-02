import { describe, expect, it } from "vitest";
import {
  historyStatusLabel,
  isAuthoritativePayment,
  paymentStatusLabel,
  phaseForPaymentStatus,
} from "./paymentLifecycle";

describe("payment lifecycle presentation", () => {
  it("does not treat signature verification as authoritative completion", () => {
    expect(isAuthoritativePayment("signature_verified", "awaiting_signed_webhook")).toBe(false);
    expect(phaseForPaymentStatus("signature_verified", "awaiting_signed_webhook")).toBe(
      "awaiting_authoritative_status",
    );
    expect(paymentStatusLabel("signature_verified")).toContain("awaiting payment status");
  });

  it("recognizes only recorded terminal payment states as authoritative", () => {
    expect(phaseForPaymentStatus("captured", "recorded_approved")).toBe("payment_complete");
    expect(phaseForPaymentStatus("failed", "recorded_declined")).toBe("failure");
    expect(phaseForPaymentStatus("captured", "pending")).toBeNull();
  });

  it("formats unknown statuses without inventing lifecycle meaning", () => {
    expect(paymentStatusLabel("future_gateway_state")).toBe("future gateway state");
    expect(historyStatusLabel(undefined)).toBe("not recorded");
  });
});
