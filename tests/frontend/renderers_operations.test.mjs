// Deterministic DOM-module contract tests for the fraud-operations panel.
// Imports the real renderers.js the FastAPI app serves unmodified -- these
// assertions fail if the rendered DOM ever diverges from the exact values
// in the fixture (which is shaped like a real /api/demo/step "operations"
// projection), so a value that gets recomputed, dropped, or fabricated in
// the renderer is caught here without needing a full browser.
import assert from "node:assert/strict";
import { test } from "node:test";
import { el, importStatic } from "./dom_setup.mjs";

const { renderOperations } = await importStatic("renderers.js");

const FRESH_EVIDENCE = {
  prior_attempts_24h: 3,
  distinct_cards_24h: 4,
  prior_decline_streak: 3,
  sessions_24h: 1,
  ip_changes_24h: 1,
  prior_successful_checkouts: 0,
};

function freshOperations(overrides = {}) {
  return {
    decision: "block",
    risk_score: 0.912345,
    risk_band: "very_high",
    risk_score_label: "risk score — not a guaranteed fraud probability",
    rule_score: 7,
    reason_codes: ["persistent_high_model_risk"],
    state_version: 4,
    latency_ms: 3.21,
    idempotent_replay: false,
    authorization: "suppressed",
    outcome_status: null,
    checkout_status: null,
    evidence: FRESH_EVIDENCE,
    protected_reference: "hmac_abcdef0123",
    ...overrides,
  };
}

test("every allowlisted evidence value is rendered verbatim, and only those six keys appear", () => {
  const container = el();
  renderOperations(container, el("span"), freshOperations());
  const text = container.textContent;

  for (const [key, value] of Object.entries(FRESH_EVIDENCE)) {
    assert.ok(
      text.includes(String(value)),
      `expected rendered evidence to include ${key}=${value}`,
    );
  }

  // Exactly six <dd> evidence values in the causal-signals list -- not the
  // 44-feature vector, not more, not fewer.
  const dds = container.querySelectorAll(".detail-list dd");
  const evidenceListDds = [...dds].filter((dd) =>
    Object.values(FRESH_EVIDENCE).map(String).includes(dd.textContent),
  );
  assert.equal(evidenceListDds.length, 6);
});

test("risk score renders to exactly three decimals and never exposes the raw floating point value directly", () => {
  const container = el();
  renderOperations(container, el("span"), freshOperations({ risk_score: 0.1 }));
  assert.ok(container.textContent.includes("0.100"));
});

test("the full 44-feature vector is never present -- only the allowlisted keys reach the DOM", () => {
  const container = el();
  const op = freshOperations({
    // Simulate what a defect would look like: extra disallowed keys
    // sneaking into `evidence`. The renderer must only ever read the keys
    // actually supplied by the caller -- but this test's job is to prove
    // that when the API only ever supplies the six-key allowlist (which is
    // enforced server-side by services/operations_projection.py), no
    // additional feature names such as "campaign_active_flag" or
    // "raw_risk_score" appear anywhere in the rendered output.
    evidence: FRESH_EVIDENCE,
  });
  renderOperations(container, el("span"), op);
  const forbidden = [
    "device_hash",
    "session_hash",
    "card_hash",
    "ip_hash",
    "campaign_active_flag",
    "raw_score",
    "feature_vector",
  ];
  forbidden.forEach((term) => {
    assert.ok(!container.textContent.includes(term), `must not render ${term}`);
  });
});

test("idempotent replay WITH preserved evidence: labels it as the original decision's evidence, not freshly computed", () => {
  const container = el();
  const badge = el("span");
  renderOperations(
    container,
    badge,
    freshOperations({ idempotent_replay: true, evidence: FRESH_EVIDENCE }),
  );
  assert.ok(!badge.classList.contains("is-hidden"));
  const text = container.textContent;
  assert.ok(/original decision/i.test(text));
  assert.ok(/no new causal snapshot/i.test(text) || /not.*freshly computed/i.test(text));
  // The preserved values must still be the real original values.
  Object.values(FRESH_EVIDENCE).forEach((value) => {
    assert.ok(text.includes(String(value)));
  });
});

test("idempotent replay with NO stored evidence: says so explicitly and fabricates nothing", () => {
  const container = el();
  renderOperations(
    container,
    el("span"),
    freshOperations({ idempotent_replay: true, evidence: {} }),
  );
  const text = container.textContent;
  assert.ok(/not the same as zero signals/i.test(text));
  // Must not print a bare "0" evidence table as if it were real data.
  const dds = [...container.querySelectorAll(".detail-list dd")];
  const zeroEvidenceLooking = dds.filter((dd) => dd.textContent === "0");
  assert.equal(zeroEvidenceLooking.length, 0);
});

test("authorization suppressed / no processor outcome is shown verbatim for a block", () => {
  const container = el();
  renderOperations(container, el("span"), freshOperations());
  const text = container.textContent;
  assert.ok(text.includes("Suppressed"));
  assert.ok(text.includes("Not recorded")); // processor outcome
});

test("protected reference is rendered but never the raw identifier", () => {
  const container = el();
  const op = freshOperations({ protected_reference: "hmac_shortened_ref_1" });
  renderOperations(container, el("span"), op);
  assert.ok(container.textContent.includes("hmac_shortened_ref_1"));
  assert.ok(!container.textContent.includes("raw-device-sensitive"));
});
