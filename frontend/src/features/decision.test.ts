import { describe, expect, it } from "vitest";
import { decisionCopy, normalizePrecheck, policyV2ReasonCodes, presentReason, reasonPresentations, safeReason } from "./decision";

describe("decision presentation", () => {
  it("fails closed for reason codes outside the UI contract", () => {
    expect(safeReason("untrusted_new_reason")).toBe("Additional policy signal");
  });

  it("normalizes the backend decision without changing it", () => {
    const operation = normalizePrecheck({ request_id: "request", event_id: "event", decision: "block", risk_score: .84, rule_score: 6, reason_codes: ["sustained_request_burst"], decision_basis: "model_and_rules", model_status: "ready", device_state_version: 4, latency_ms: 2.4 });
    expect(operation.decision).toBe("block");
    expect(operation.risk_score).toBe(.84);
    expect(operation.reason_codes).toEqual(["sustained_request_burst"]);
  });

  it("provides intentional labels and explanations for every Policy v2 reason", () => {
    expect(Object.keys(reasonPresentations).sort()).toEqual([...policyV2ReasonCodes].sort());
    for (const code of policyV2ReasonCodes) {
      const presentation = presentReason(code);
      expect(presentation.label).not.toBe("Additional policy signal");
      expect(presentation.explanation.length).toBeGreaterThan(25);
    }
  });

  it("keeps ALLOW separate from payment approval", () => {
    expect(decisionCopy.allow.copy).toContain("insufficient evidence to stop");
    expect(decisionCopy.allow.copy).toContain("Payment approval still happens later through Razorpay");
    expect(decisionCopy.allow.copy).not.toMatch(/safe payment|legitimate customer|fraud-free/i);
  });

  it("describes REVIEW without inventing a review or step-up workflow", () => {
    expect(decisionCopy.review.copy).toContain("suppresses order creation");
    expect(decisionCopy.review.copy).toContain("does not operate a manual-review or step-up flow");
  });

  it("makes BLOCK attempt-scoped without claiming a timed ban", () => {
    expect(decisionCopy.block.copy).toMatch(/future attempts are independently evaluated/i);
    expect(decisionCopy.block.copy).not.toMatch(/one hour|blocked until|device ban/i);
  });
});
