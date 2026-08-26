import assert from "node:assert/strict";
import { test } from "node:test";
import { importStatic } from "./dom_setup.mjs";
import { el } from "./dom_setup.mjs";

const { customerState, explainReason, REASON_LIBRARY } = await importStatic("formatters.js");
const { renderReasons, renderTimeline } = await importStatic("renderers.js");

/* ── Customer DOM cannot receive risk score, reason codes, state version,
   or protected identifiers ── */

test("customerState() only ever returns one of the seven approved strings, never leaks operational data", () => {
  const approved = [
    "Ready to pay.",
    "Sent for authorization.",
    "Payment under review.",
    "Payment approved.",
    "Payment declined by bank.",
    "Payment blocked before authorization.",
  ];
  const adversarialOperations = {
    decision: "review",
    risk_score: 0.987654,
    risk_band: "very_high",
    rule_score: 12,
    reason_codes: ["persistent_high_model_risk"],
    state_version: 99,
    authorization: "sent",
    outcome_status: null,
    checkout_status: null,
    evidence: { prior_attempts_24h: 5 },
    protected_reference: "hmac_should_never_appear",
  };
  const result = customerState(adversarialOperations);
  assert.ok(approved.includes(result), `unexpected customer-facing string: ${result}`);
  assert.ok(!result.includes("0.987654"));
  assert.ok(!result.includes("99"));
  assert.ok(!result.includes("hmac_should_never_appear"));
  assert.ok(!result.toLowerCase().includes("risk"));
  assert.ok(!result.toLowerCase().includes("reason"));
});

test("customerState() with null operations (not yet paid) is exactly 'Ready to pay.'", () => {
  assert.equal(customerState(null), "Ready to pay.");
});

test("customerState() block -> 'Payment blocked before authorization.' regardless of any other field", () => {
  assert.equal(
    customerState({ decision: "block", risk_score: 0.99, outcome_status: null }),
    "Payment blocked before authorization.",
  );
});

/* ── Unknown reason codes fail closed ── */

test("explainReason() fails closed for an unrecognized code -- never invents a plausible explanation", () => {
  const info = explainReason("totally_made_up_reason_code_xyz");
  assert.equal(info.direction, "unrecognized");
  assert.match(info.title.toLowerCase(), /unrecognized/);
  assert.match(info.title.toLowerCase(), /not.*published.*contract/);
});

test("every real policy reason code from REASON_LIBRARY is recognized (sanity check against drift)", () => {
  const expectedCodes = [
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
  ];
  expectedCodes.forEach((code) => {
    assert.ok(REASON_LIBRARY[code], `missing library entry for ${code}`);
    assert.notEqual(explainReason(code).direction, "unrecognized");
  });
});

test("renderReasons renders the unrecognized styling class for an unknown code, not a fabricated known-looking one", () => {
  const container = el();
  renderReasons(container, ["not_a_real_code"], { heading: "Evidence supporting this action" });
  const item = container.querySelector(".reason-item");
  assert.ok(item.classList.contains("unrecognized"));
});

/* ── Block lifecycle text is exact ── */

test("a block row's lifecycle text matches the required exact wording", () => {
  const container = el();
  const items = [
    {
      event_type: "authorization_request",
      decision: "block",
      request_index: 1,
      calibrated_probability: 0.95,
      timestamp: "2030-01-01T00:00:00+00:00",
      state_version: 4,
    },
  ];
  renderTimeline(container, items, { lifecycleText: true });
  const text = container.querySelector(".timeline-lifecycle").textContent;
  assert.equal(text, "Authorization suppressed. Bank not contacted. No outcome event created.");
});

test("an allow row with a later attempt after a block is still rendered with real (not fabricated) lifecycle text", () => {
  const container = el();
  const items = [
    {
      event_type: "authorization_request",
      decision: "block",
      request_index: 1,
      calibrated_probability: 0.95,
      timestamp: "2030-01-01T00:00:00+00:00",
    },
    {
      event_type: "authorization_request",
      decision: "allow",
      request_index: 2,
      calibrated_probability: 0.2,
      timestamp: "2030-01-01T00:05:00+00:00",
    },
    {
      event_type: "authorization_outcome",
      request_id: "req-2",
      authorization_result: "approved",
      timestamp: "2030-01-01T00:05:01+00:00",
    },
  ];
  renderTimeline(container, items, { lifecycleText: true });
  const cards = container.querySelectorAll(".timeline-item");
  assert.equal(cards.length, 2);
  assert.equal(
    cards[1].querySelector(".timeline-lifecycle").textContent,
    "Sent for authorization. Bank approved.",
  );
});
