/* Live Traffic console: honest rendering of the merchant risk feed.

   These import the exact modules FastAPI serves at /static/*.js and drive
   them against a real jsdom DOM. The recurring theme is that the console
   may only display what the backend actually produced -- no fabricated card
   digits, no invented lifecycle result, no ground truth on a decision. */
import assert from "node:assert/strict";
import { test } from "node:test";
import { el, importStatic } from "./dom_setup.mjs";

const renderers = await importStatic("renderers.js");
const formatters = await importStatic("formatters.js");

function payment(overrides = {}, opOverrides = {}) {
  return {
    sequence: 4,
    device_key: "dev-05",
    attempt: 4,
    amount: 5.0,
    currency: "INR",
    card_alias: "Card #04",
    campaign_active: false,
    virtual_timestamp: "2030-01-01T00:02:39+00:00",
    virtual_offset_seconds: 159,
    operations: {
      decision: "block",
      risk_score: 0.8642,
      risk_band: "very_high",
      risk_score_label: "risk score — not a guaranteed fraud probability",
      rule_score: 6,
      reason_codes: [
        "rule_corroborated_block",
        "high_risk_with_card_diversity",
        "high_risk_with_card_switching",
        "high_risk_with_ip_rotation",
        "persistent_high_model_risk",
        "cross_session_card_diversity",
      ],
      state_version: 4,
      latency_ms: 2.31,
      idempotent_replay: false,
      authorization: "suppressed",
      outcome_status: null,
      checkout_status: null,
      evidence: {
        prior_attempts_24h: 3,
        distinct_cards_24h: 4,
        prior_decline_streak: 3,
        sessions_24h: 1,
        ip_changes_24h: 1,
        prior_successful_checkouts: 0,
      },
      protected_reference: "a91f20c4d7e8b3164c02",
      ...opOverrides,
    },
    ...overrides,
  };
}

test("a feed row renders only backend-supplied values and never fabricates card digits", () => {
  const row = renderers.trafficRow(payment());
  const text = row.textContent;
  assert.ok(text.includes("Card #04"));
  // A masked PAN would be a lie: the backend holds an HMAC fingerprint and
  // never a card number, so there is no last-four to show.
  assert.ok(!/•{2,}/.test(text), "must not render fabricated masked digits");
  assert.ok(!/\d{4}\s*$/.test(row.querySelector(".feed-card").textContent));
  assert.equal(row.querySelector(".feed-action").textContent, "block");
  assert.equal(row.querySelector(".feed-device").textContent, "dev-05");
});

test("the feed shows compressed virtual elapsed time, never wall-clock now", () => {
  const row = renderers.trafficRow(payment());
  const shown = row.querySelector(".feed-time").textContent;
  assert.equal(shown, formatters.virtualElapsed(159));
  assert.equal(shown, "02:39");
  const wallClock = new Date().toLocaleTimeString();
  assert.notEqual(shown, wallClock);
});

test("virtualElapsed escalates to hours and days rather than flattening a long horizon", () => {
  assert.equal(formatters.virtualElapsed(45), "00:45");
  assert.equal(formatters.virtualElapsed(3600 * 6 + 120), "6h 02m");
  assert.ok(formatters.virtualElapsed(86400 * 2 + 3600).startsWith("D3"));
  assert.equal(formatters.virtualElapsed(-1), "—");
  assert.equal(formatters.virtualElapsed("nope"), "—");
});

test("risk detail shows at most five reasons up front and keeps the rest reachable", () => {
  const node = el();
  renderers.renderRiskDetail(node, payment());
  const primary = node.querySelectorAll(".ops-section > .reason-list > .reason-item");
  assert.equal(primary.length, 5);
  const more = node.querySelector(".reason-more");
  assert.ok(more, "the sixth contracted reason must remain reachable, not dropped");
  assert.equal(more.querySelectorAll(".reason-item").length, 1);
});

test("risk detail keeps the full 44-feature vector out of the DOM", () => {
  const node = el();
  renderers.renderRiskDetail(node, payment());
  const text = node.textContent;
  ["prior_attempts_5m", "amount_variation_24h", "ip_rotation_ratio_24h", "distinct_bins_5m"].forEach(
    (name) => assert.ok(!text.includes(name), `${name} must not reach the DOM`),
  );
  assert.ok(text.includes("Six allowlisted causal signals"));
});

test("risk detail fails closed on an uncontracted reason code", () => {
  const node = el();
  renderers.renderRiskDetail(node, payment({}, { reason_codes: ["totally_made_up_code"] }));
  assert.ok(node.querySelector(".reason-item.unrecognized"));
  assert.ok(/not in the published contract/i.test(node.textContent));
});

test("a blocked payment reports suppression and no processor outcome", () => {
  const node = el();
  renderers.renderRiskDetail(node, payment());
  assert.ok(node.textContent.includes("Suppressed before authorization"));
});

test("a decided-but-not-yet-settled payment says awaiting, it does not invent a result", () => {
  const pending = payment({}, { decision: "allow", outcome_status: null, authorization: "sent" });
  assert.equal(
    formatters.lifecycleSummary(pending.operations),
    "Sent · awaiting processor outcome",
  );
  const settled = payment({}, { decision: "allow", outcome_status: "approved", authorization: "sent" });
  assert.equal(formatters.lifecycleSummary(settled.operations), "Approved by bank");
});

test("risk trajectory reports first intervention from the decisions themselves", () => {
  const attempts = [0.11, 0.34, 0.59, 0.88].map((score, index) =>
    payment(
      { attempt: index + 1, sequence: index + 1, virtual_offset_seconds: index * 40 },
      {
        risk_score: score,
        decision: score >= 0.8 ? "block" : score >= 0.5 ? "review" : "allow",
        reason_codes: [],
      },
    ),
  );
  const node = el();
  renderers.renderTrajectory(node, "dev-05", attempts);
  const text = node.textContent;
  assert.ok(text.includes("Attempt 3"));
  const summary = [...node.querySelectorAll(".trajectory-summary dd")].map((d) => d.textContent);
  assert.deepEqual(summary, ["4", "Attempt 3", "Attempt 4", "01:20"]);
});

test("run totals render exactly the four run-scoped counters", () => {
  const node = el();
  renderers.renderRunTotals(node, { payments: 42, allow: 35, review: 4, block: 3 });
  const labels = [...node.querySelectorAll(".run-total span")].map((s) => s.textContent);
  const values = [...node.querySelectorAll(".run-total strong")].map((s) => s.textContent);
  assert.deepEqual(labels, ["Payments", "Allowed", "Reviewed", "Blocked"]);
  assert.deepEqual(values, ["42", "35", "4", "3"]);
});

test("ground truth labels a missed attacker and a false positive honestly", () => {
  const node = el();
  renderers.renderTruth(node, {
    devices: [
      { device_key: "dev-01", scenario_label: "Everyday Checkout", is_attack: false, detected: false, first_review_attempt: null, first_block_attempt: null },
      { device_key: "dev-02", scenario_label: "Everyday Checkout", is_attack: false, detected: true, first_review_attempt: 3, first_block_attempt: null },
      { device_key: "dev-05", scenario_label: "Burst Card Testing", is_attack: true, detected: true, first_review_attempt: 4, first_block_attempt: 4 },
      { device_key: "dev-06", scenario_label: "Patient Card Testing", is_attack: true, detected: false, first_review_attempt: null, first_block_attempt: null },
    ],
    disclosure: "Ground truth is held only by the simulator.",
  });
  const verdicts = [...node.querySelectorAll(".truth-verdict")].map((n) => n.textContent);
  assert.deepEqual(verdicts, ["No action", "False positive", "Detected", "Missed"]);
  assert.ok(node.textContent.includes("held only by the simulator"));
});

test("the empty detail panel prompts a selection instead of showing a placeholder score", () => {
  const node = el();
  renderers.renderRiskDetail(node, null);
  assert.ok(node.textContent.includes("Select a payment"));
  assert.ok(!/0\.000/.test(node.textContent));
});

test("scenario descriptions never state an expected decision", () => {
  Object.entries(formatters.SCENARIO_LIBRARY).forEach(([id, text]) => {
    ["allow", "review", "block", "detected", "will be", "expected"].forEach((term) => {
      assert.ok(!text.toLowerCase().includes(term), `${id} description leaks "${term}"`);
    });
  });
});

test("a long-horizon replay is grouped by virtual day instead of reading as one sitting", () => {
  const step = (attempt, elapsed) => ({
    attempt: { attempt, elapsed_seconds: elapsed, card_alias: "Card #01", timestamp: null },
    operations: {
      decision: "allow", risk_score: 0.2, state_version: attempt,
      idempotent_replay: false, outcome_status: "declined", checkout_status: null,
    },
  });
  const node = el();
  renderers.renderAuthoritativeTimeline(node, [
    step(1, 0), step(2, 21600), step(3, 108000), step(4, 205200),
  ]);
  const days = [...node.querySelectorAll(".timeline-day")].map((n) => n.textContent);
  assert.deepEqual(days, ["Day 1 · simulated", "Day 2 · simulated", "Day 3 · simulated"]);
  assert.equal(node.querySelectorAll(".transaction-row").length, 4);
});

test("a same-day replay gets no day headers at all", () => {
  const step = (attempt, elapsed) => ({
    attempt: { attempt, elapsed_seconds: elapsed, card_alias: "Card #01", timestamp: null },
    operations: {
      decision: "allow", risk_score: 0.1, state_version: attempt,
      idempotent_replay: false, outcome_status: "approved", checkout_status: null,
    },
  });
  const node = el();
  renderers.renderAuthoritativeTimeline(node, [step(1, 0), step(2, 95)]);
  assert.equal(node.querySelectorAll(".timeline-day").length, 0);
  assert.equal(node.querySelectorAll(".transaction-row").length, 2);
});

test("groupByVirtualDay keeps every step and never reorders them", () => {
  const steps = [0, 100, 90000, 90100, 180000].map((elapsed, i) => ({
    attempt: { attempt: i + 1, elapsed_seconds: elapsed },
    operations: { decision: "allow" },
  }));
  const groups = renderers.groupByVirtualDay(steps);
  const flattened = groups.flatMap((g) => g.steps);
  assert.equal(flattened.length, steps.length);
  assert.deepEqual(flattened.map((s) => s.attempt.attempt), [1, 2, 3, 4, 5]);
  assert.deepEqual(groups.map((g) => g.day), [1, 2, 3]);
});
