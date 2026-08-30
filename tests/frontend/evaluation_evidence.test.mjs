/* Frozen evaluation rendering.

   The recurring rule: the page may only state what the frozen artifact
   actually supports. A recall figure never appears without its cost, and a
   dominance claim is rendered only while the artifact still backs it. */
import assert from "node:assert/strict";
import { test } from "node:test";
import { el, importStatic } from "./dom_setup.mjs";

const renderers = await importStatic("renderers.js");
const formatters = await importStatic("formatters.js");

function payment(overrides = {}, opOverrides = {}) {
  return {
    sequence: 1, device_key: "dev-05", attempt: 4, amount: 5, currency: "INR",
    card_alias: "Card #04", virtual_offset_seconds: 159,
    operations: {
      decision: "block", risk_score: 0.86, risk_band: "very_high", rule_score: 6,
      reason_codes: ["persistent_high_model_risk"], state_version: 4, latency_ms: 2.3,
      idempotent_replay: false, authorization: "suppressed", outcome_status: null,
      checkout_status: null, evidence: { prior_attempts_24h: 3 },
      protected_reference: "a91f", ...opOverrides,
    },
    ...overrides,
  };
}

const COMPARISON = {
  schema_version: "card-testing-sentinel-baseline-comparison-1",
  baselines: [
    { id: "count_ge_5", family: "request_count", label: "Count ≥5 requests", attacker_recall: 0.98, attacker_detected: 294, attacker_devices: 300, legitimate_false_positive_rate: 0.016470588, legitimate_flagged: 28, legitimate_devices: 1700 },
    { id: "count_ge_10", family: "request_count", label: "Count ≥10 requests", attacker_recall: 0.303333, attacker_detected: 91, attacker_devices: 300, legitimate_false_positive_rate: 0, legitimate_flagged: 0, legitimate_devices: 1700 },
    { id: "rules_ge_3", family: "rules_only", label: "Rules only ≥3 points", attacker_recall: 0.623333, attacker_detected: 187, attacker_devices: 300, legitimate_false_positive_rate: 0.012352941, legitimate_flagged: 21, legitimate_devices: 1700 },
    { id: "sentinel_review_or_higher", family: "sentinel", label: "Sentinel (review or higher)", is_sentinel: true, attacker_recall: 0.903333, attacker_detected: 271, attacker_devices: 300, legitimate_false_positive_rate: 0.001176470, legitimate_flagged: 2, legitimate_devices: 1700 },
  ],
  dominance: { sentinel_id: "sentinel_review_or_higher", dominated: false, dominating_baselines: [], statement: "No tested threshold of either simple baseline beats Sentinel on both attacker recall and legitimate-user impact." },
};

const FAILURES = {
  attacker_devices: 300,
  never_detected: 29,
  detected_within_three_attempts: 0,
  by_subtype: [
    { subtype: "burst", label: "Burst card testing", devices: 120, review_or_higher_rate: 1, block_rate: 0.941666, never_detected: 0 },
    { subtype: "evasive", label: "Evasive card testing", devices: 90, review_or_higher_rate: 0.877777, block_rate: 0.722222, never_detected: 11 },
    { subtype: "patient", label: "Patient card testing", devices: 90, review_or_higher_rate: 0.8, block_rate: 0.611111, never_detected: 18 },
  ],
};

test("the baseline table renders every approach with both axes", () => {
  const node = el();
  renderers.renderBaselineTable(node, COMPARISON);
  const rows = [...node.querySelectorAll("tbody tr")];
  assert.equal(rows.length, 4);
  const first = [...rows[0].querySelectorAll("td")].map((c) => c.textContent);
  assert.equal(first[0], "Count ≥5 requests");
  assert.equal(first[1], "98.0%");
  assert.equal(first[2], "28 of 1700 · 1.65%");
});

test("the Sentinel row is marked but the losing columns stay readable", () => {
  const node = el();
  renderers.renderBaselineTable(node, COMPARISON);
  const sentinel = node.querySelectorAll("tr.is-sentinel");
  assert.equal(sentinel.length, 1);
  assert.ok(sentinel[0].textContent.includes("Sentinel"));
  // count >=10 has a LOWER false-positive rate than Sentinel; the table must
  // still show it rather than hiding an unflattering comparison.
  assert.ok(node.textContent.includes("0 of 1700 · 0.00%"));
});

test("a baseline table with no artifact says so instead of rendering an empty shell", () => {
  const node = el();
  renderers.renderBaselineTable(node, null);
  assert.ok(/no baseline comparison artifact/i.test(node.textContent));
  assert.equal(node.querySelectorAll("table").length, 0);
});

test("failure modes report every subtype and name the worst one", () => {
  const node = el();
  renderers.renderFailureModes(node, FAILURES);
  const rows = [...node.querySelectorAll("tbody tr")].map((r) => r.textContent);
  assert.equal(rows.length, 3);
  assert.ok(rows[0].includes("100.0%"));
  const summary = node.querySelector(".evidence-note").textContent;
  assert.ok(summary.includes("29 of 300"));
  assert.ok(summary.includes("patient card testing"));
  assert.ok(summary.includes("first three attempts"));
});

test("block rate never renders above review-or-higher rate for a subtype", () => {
  const node = el();
  renderers.renderFailureModes(node, FAILURES);
  FAILURES.by_subtype.forEach((row) => {
    assert.ok(row.block_rate <= row.review_or_higher_rate, row.subtype);
  });
});

test("metric list marks a primary metric so block rate reads as secondary", () => {
  const node = el("dl");
  renderers.renderMetricList(node, [
    { label: "Review or higher", value: "90.33%", emphasis: true },
    { label: "Blocked", value: "77.67%" },
  ]);
  const primary = node.querySelectorAll("dd.is-primary");
  assert.equal(primary.length, 1);
  assert.equal(primary[0].textContent, "90.33%");
  assert.equal(node.querySelectorAll("dt").length, 2);
});

test("metric list renders a note without breaking the label/value pairing", () => {
  const node = el("dl");
  renderers.renderMetricList(node, [
    { label: "Reviewed", value: "2 of 1,700", note: "Both were bad-luck retry devices." },
  ]);
  assert.equal(node.querySelectorAll("dt").length, 2);
  assert.equal(node.querySelectorAll("dd").length, 2);
  assert.ok(node.querySelector("dd.metric-note").textContent.includes("bad-luck"));
});

test("a saturated calibrator score is shown honestly, not dressed up as >0.999", () => {
  // Isotonic calibration maps its top bin to exactly 1.0. Rendering ">0.999"
  // would invent precision the calibrator does not have.
  assert.equal(formatters.riskScore(1), "1.000");
  assert.equal(formatters.isSaturated(1), true);
  assert.equal(formatters.isSaturated(0.9999), false);
});

test("a tiny non-zero score is not flattened to 0.000", () => {
  // This one IS a display artifact: 0.000 makes a probabilistic model look
  // like a step function when the score is small but real.
  assert.equal(formatters.riskScore(0.0001), "<0.001");
  assert.equal(formatters.riskScore(0), "0.000");
  assert.equal(formatters.riskScore(0.0006), "0.001");
});

test("the detail panel explains a saturated score instead of leaving 1.000 bare", () => {
  const node = el();
  renderers.renderRiskDetail(node, payment({}, { risk_score: 1 }));
  assert.ok(/top bin of the isotonic calibrator/i.test(node.textContent));
  assert.ok(!/certainty\./i.test(node.textContent.replace(/not a claim of certainty/i, "")));
});

test("an ordinary score gets no saturation note", () => {
  const node = el();
  renderers.renderRiskDetail(node, payment({}, { risk_score: 0.86 }));
  assert.ok(!/isotonic calibrator/i.test(node.textContent));
});


test("the visible table can be narrowed to the rows that carry the argument", () => {
  // Overview shows four rows; the full sweep stays available behind a
  // disclosure rather than being dropped.
  const node = el();
  renderers.renderBaselineTable(node, COMPARISON, {
    only: ["count_ge_5", "sentinel_review_or_higher"],
  });
  const labels = [...node.querySelectorAll("tbody td:first-child")].map((c) => c.textContent);
  assert.deepEqual(labels, ["Count ≥5 requests", "Sentinel (review or higher)"]);
  // and without the filter every row is still rendered
  const full = el();
  renderers.renderBaselineTable(full, COMPARISON);
  assert.equal(full.querySelectorAll("tbody tr").length, COMPARISON.baselines.length);
});

test("the weakest attack subtype is marked so the hardest case is findable", () => {
  const node = el();
  renderers.renderFailureModes(node, FAILURES);
  const weakest = node.querySelector("tr.is-weakest");
  assert.ok(weakest, "the lowest-recall subtype must be marked");
  assert.ok(weakest.textContent.includes("Patient"));
  assert.ok(weakest.textContent.includes("weakest"));
  assert.equal(node.querySelectorAll("tr.is-weakest").length, 1);
});

test("the chart labels the desirable direction", () => {
  const node = el();
  renderers.renderBaselineChart(node, COMPARISON);
  assert.ok(/better/.test(node.querySelector(".tc-direction").textContent));
});
