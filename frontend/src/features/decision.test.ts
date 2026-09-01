import { describe, expect, it } from "vitest";
import { normalizePrecheck, safeReason } from "./decision";

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
});
