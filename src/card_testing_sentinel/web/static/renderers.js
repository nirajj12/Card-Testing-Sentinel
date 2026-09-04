import {
  clockTime,
  currency,
  percent,
  explainReason,
  latency,
  isSaturated,
  lifecycleSummary,
  riskScore,
  shortId,
  titleCase,
  virtualDay,
  virtualElapsed,
} from "./formatters.js";

export function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

export function clear(node) {
  node.replaceChildren();
}

const SAFE_SIGNALS = [
  ["prior_attempts_24h", "Recent attempts"],
  ["distinct_cards_24h", "Recent distinct cards"],
  ["prior_decline_streak", "Decline streak"],
  ["sessions_24h", "Session count"],
  ["ip_changes_24h", "IP changes"],
  ["prior_successful_checkouts", "Previous successful checkouts"],
];

export function reasonsHeading(decision) {
  return decision === "allow" ? "Signals observed" : "Evidence supporting this action";
}

export function renderReasons(container, reasons, options = {}) {
  clear(container);
  if (options.heading) container.append(element("h4", null, options.heading));
  const list = element("div", "reason-list");
  if (!reasons?.length) {
    list.append(element("p", "reason-empty", "No elevated policy reason was emitted for this request."));
    container.append(list);
    return;
  }
  /* `options.limit` is opt-in. Without it every contracted reason is
     rendered exactly as before -- the operations panel and its tests rely
     on that. The Live Traffic detail panel passes a limit so the primary
     surface shows the 3-5 that carried the decision, with the remainder
     still reachable rather than dropped. */
  const shown = options.limit ? reasons.slice(0, options.limit) : reasons;
  const hidden = options.limit ? reasons.slice(options.limit) : [];
  shown.forEach((code) => {
    const info = explainReason(code);
    const item = element("div", `reason-item ${info.direction}`);
    item.append(
      element("p", "reason-title", info.title),
      element("p", "reason-text", info.text),
      element("p", "reason-code-raw", code),
    );
    list.append(item);
  });
  container.append(list);
  if (hidden.length) {
    const more = element("details", "reason-more");
    more.append(element("summary", null, `${hidden.length} further contracted reason${hidden.length === 1 ? "" : "s"}`));
    const rest = element("div", "reason-list");
    hidden.forEach((code) => {
      const info = explainReason(code);
      const item = element("div", `reason-item ${info.direction}`);
      item.append(
        element("p", "reason-title", info.title),
        element("p", "reason-text", info.text),
        element("p", "reason-code-raw", code),
      );
      rest.append(item);
    });
    more.append(rest);
    container.append(more);
  }
}

function lifecycleValue(value, fallback) {
  return value ? titleCase(value) : fallback;
}

export function renderOperations(container, badge, op) {
  clear(container);
  badge.classList.toggle("is-hidden", !op?.idempotent_replay);
  if (!op) {
    const empty = element("div", "operations-empty");
    empty.append(
      element("span", "empty-shield", "◇"),
      element("strong", null, "Waiting for a payment request"),
      element("p", null, "Start a scenario, then submit an attempt to see the authoritative risk decision."),
    );
    container.append(empty);
    return;
  }

  const summary = element("div", "decision-summary");
  summary.append(element("span", `decision-badge ${op.decision}`, op.decision));
  const score = element("div", "risk-score-block");
  score.append(element("small", null, "Risk score"), element("strong", null, riskScore(op.risk_score)));
  const band = element("div", "risk-band");
  band.append(element("small", null, `${op.rule_score} of 10 behavioural rule points`), element("strong", null, `${titleCase(op.risk_band)} band`));
  summary.append(score, band);
  container.append(summary);
  container.append(element("p", "score-disclaimer", op.risk_score_label || "Risk score — not a guaranteed fraud probability."));

  if (op.idempotent_replay) {
    container.append(element("p", "replay-notice", "Stored idempotent replay. The original decision and state version were preserved; no new causal snapshot was calculated."));
  }

  const signalSection = element("section", "ops-section");
  signalSection.append(element("h4", null, reasonsHeading(op.decision)));
  const signals = element("dl", "signal-grid detail-list");
  let signalCount = 0;
  SAFE_SIGNALS.forEach(([key, label]) => {
    if (!Object.hasOwn(op.evidence || {}, key)) return;
    const item = element("div", "signal-item");
    item.append(element("dt", null, label), element("dd", null, op.evidence[key]));
    signals.append(item);
    signalCount += 1;
  });
  if (signalCount) signalSection.append(signals);
  else signalSection.append(element("p", "reason-empty", op.idempotent_replay ? "No evidence was stored for the original decision. This is not the same as zero signals." : "No safe causal signals are available for this attempt."));
  container.append(signalSection);

  const reasonSection = element("section", "ops-section");
  /* Distinct from the signal grid above it -- one shows the measured causal
     signals, the other shows which contracted policy reasons fired. */
  renderReasons(reasonSection, op.reason_codes, { heading: "Policy reasons" });
  container.append(reasonSection);

  const lifecycle = element("section", "ops-section");
  lifecycle.append(element("h4", null, "Request lifecycle"));
  const cells = element("div", "ops-lifecycle");
  const authorization = op.authorization === "sent" ? "Sent to processor" : "Suppressed";
  [
    ["Authorization", authorization],
    ["Processor outcome", lifecycleValue(op.outcome_status, "Not recorded")],
    ["Checkout", lifecycleValue(op.checkout_status, "Not completed")],
  ].forEach(([label, value]) => {
    const cell = element("div", "lifecycle-cell");
    cell.append(element("small", null, label), element("strong", null, value));
    cells.append(cell);
  });
  lifecycle.append(cells);
  container.append(lifecycle);

  const footer = element("div", "ops-footer");
  const values = [
    ["State", `v${op.state_version}`],
    ["Latency", latency(op.latency_ms)],
    ["Protected request ref", op.protected_reference || "—"],
  ];
  values.forEach(([label, value]) => {
    const item = element("span");
    item.append(document.createTextNode(`${label} `), element("code", null, value));
    footer.append(item);
  });
  container.append(footer);
}

export function renderCustomerStatus(node, text) {
  const target = node.querySelector?.("[data-customer-status]") || node;
  target.textContent = text;
}

function rawGroupAttempts(items) {
  const attempts = [];
  const byRequest = new Map();
  items.forEach((item) => {
    const isRequest = !item.event_type || item.event_type === "authorization_request";
    if (isRequest && (item.decision || item.action)) {
      const group = { request: item, events: [] };
      attempts.push(group);
      if (item.request_id) byRequest.set(item.request_id, group);
    } else {
      const group = byRequest.get(item.request_id) || attempts.at(-1);
      if (group) group.events.push(item);
    }
  });
  return attempts;
}

function lifecycleText(action, events) {
  if (action === "block" || action === "review") return "Authorization suppressed. Bank not contacted. No outcome event created.";
  const outcome = events.find((event) => event.authorization_result);
  const checkout = events.find((event) => event.event_type === "checkout_completion");
  const prefix = action === "review" ? "Sent for authorization (under review)." : "Sent for authorization.";
  if (!outcome) return `${prefix} Bank outcome not yet recorded.`;
  if (outcome.authorization_result === "approved") return checkout ? `${prefix} Bank approved. Checkout completed.` : `${prefix} Bank approved.`;
  return `${prefix} Bank declined this attempt.`;
}

/* Kept for API/replay contract tests and technical consumers. */
export function renderTimeline(container, items, options = {}) {
  clear(container);
  const attempts = rawGroupAttempts(items || []);
  if (!attempts.length) {
    container.append(element("p", "timeline-empty", options.empty || "No scored attempts yet."));
    return;
  }
  attempts.forEach((group, index) => {
    const row = group.request;
    const action = row.decision || row.action || "allow";
    const number = row.request_index || index + 1;
    const card = element("article", `timeline-item ${action}`);
    if (options.currentIndex === index) card.classList.add("is-current");
    card.append(
      element("span", "timeline-index", `Attempt ${number}`),
      element("p", "timeline-action", action),
      element("p", "timeline-score", riskScore(row.calibrated_probability ?? row.risk_score)),
    );
    if (row.timestamp) card.append(element("p", "timeline-meta", clockTime(row.timestamp)));
    if (options.lifecycleText) card.append(element("p", "timeline-lifecycle", lifecycleText(action, group.events)));
    container.append(card);
  });
}

function authoritativeLifecycle(op) {
  if (op.decision === "block") return "Authorization suppressed. Bank not contacted. No outcome event created.";
  const prefix = op.decision === "review" ? "Authorization sent under review." : "Authorization sent.";
  if (op.outcome_status === "approved") return op.checkout_status === "completed" ? `${prefix} Bank approved. Checkout completed.` : `${prefix} Bank approved.`;
  if (op.outcome_status === "declined") return `${prefix} Bank declined this attempt.`;
  return `${prefix} No processor outcome recorded yet.`;
}

export function renderAuthoritativeTimeline(container, steps, options = {}) {
  clear(container);
  if (!steps?.length) {
    container.append(element("p", "timeline-empty", "Start a replay to create the first causally scored attempt."));
    return;
  }
  /* Long-horizon plans (patient card testing) genuinely span days of virtual
     time. Flattening them into one continuous list would imply everything
     happened in a single sitting, which is the opposite of what makes the
     behaviour hard to catch. Day headers appear only when a run actually
     crosses a day boundary. */
  const groups = groupByVirtualDay(steps);
  const multiDay = groups.length > 1;
  let index = 0;
  groups.forEach((group) => {
    if (multiDay) {
      container.append(element("p", "timeline-day", `Day ${group.day} · simulated`));
    }
    group.steps.forEach((step) => {
      container.append(timelineRow(step, index, { ...options, multiDay }));
      index += 1;
    });
  });
}

function timelineRow(step, index, options) {
  const op = step.operations;
  const attempt = step.attempt;
  const row = element("article", "transaction-row");
  if (options.currentIndex === index) row.classList.add("is-current");
  const primary = element("div", "timeline-primary");
  /* Across a multi-day plan the absolute clock crosses real midnight while
     the day counter runs from the start of the run, so the two would appear
     to disagree. Elapsed time is what the day headers are counting. */
  const when = options.multiDay
    ? virtualElapsed(attempt.elapsed_seconds || 0)
    : attempt.timestamp
      ? clockTime(attempt.timestamp)
      : `+${attempt.elapsed_seconds || 0}s`;
  primary.append(element("strong", null, `Attempt ${attempt.attempt}`), element("span", null, when));
  const secondary = element("div", "timeline-secondary");
  secondary.append(element("strong", null, attempt.card_alias || "Synthetic card"), element("span", null, `State v${op.state_version}`));
  const score = element("div", "timeline-score", riskScore(op.risk_score));
  const lifecycle = element("div", "timeline-lifecycle-cell");
  lifecycle.append(element("p", "timeline-lifecycle", authoritativeLifecycle(op)));
  if (op.idempotent_replay) lifecycle.append(element("span", "timeline-replay", "Stored retry: original decision and state preserved; no fresh snapshot calculated."));
  row.append(
    element("span", "timeline-index", attempt.attempt),
    primary,
    secondary,
    element("span", `timeline-decision ${op.decision}`, op.decision),
    score,
    lifecycle,
  );
  return row;
}

/* Legacy console helpers remain available even though the research console is no longer in the main page. */
export function renderDecision(container, decision) {
  clear(container);
  if (!decision) return;
  container.append(element("span", `decision-badge ${decision.decision}`, decision.decision), element("strong", null, riskScore(decision.risk_score)));
}

export function renderDetails(container, values) {
  clear(container);
  Object.entries(values).forEach(([label, value]) => container.append(element("dt", null, label), element("dd", value?.mono ? "mono" : null, value?.text ?? value ?? "—")));
}

export function renderDecisionsTable(tbody, rows, onSelect) {
  clear(tbody);
  rows.forEach((item) => {
    const row = element("tr");
    row.append(element("td", null, shortId(item.request_id)), element("td", null, item.decision), element("td", null, riskScore(item.risk_score)));
    row.addEventListener("click", () => onSelect?.(item));
    tbody.append(row);
  });
}

export function renderJson(pre, value) {
  pre.textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2);
}

export function renderJsonPlaceholder(pre, text) {
  pre.textContent = text;
}


/* ────────────────────────────────────────────────────────────────────────
   Live Traffic console
   ──────────────────────────────────────────────────────────────────────── */

/* One row in the merchant payment feed. Every value comes from the traffic
   step response; nothing is derived, inferred or invented here. The device
   column shows the simulator's own device label (`dev-04`) -- the backend
   only ever holds an HMAC fingerprint, so there is no raw identifier to
   leak and no last-four to fabricate. */
export function trafficRow(payment) {
  const op = payment.operations;
  const row = element("button", `feed-row ${op.decision}`);
  row.type = "button";
  row.dataset.sequence = String(payment.sequence);
  row.dataset.device = payment.device_key;
  row.setAttribute(
    "aria-label",
    `Payment ${payment.sequence}, device ${payment.device_key}, risk ${riskScore(op.risk_score)}, ${op.decision}`,
  );
  row.append(
    element("span", "feed-time", virtualElapsed(payment.virtual_offset_seconds)),
    element("span", "feed-amount", currency(payment.amount, payment.currency)),
    element("span", "feed-device", payment.device_key),
    element("span", "feed-card", payment.card_alias),
    element("span", "feed-risk", riskScore(op.risk_score)),
    element("span", `feed-action ${op.decision}`, op.decision),
  );
  return row;
}

export function appendTrafficRow(container, payment, onSelect) {
  const empty = container.querySelector(".feed-empty");
  if (empty) empty.remove();
  const row = trafficRow(payment);
  row.addEventListener("click", () => onSelect?.(payment));
  container.prepend(row);
  return row;
}

export function renderRunTotals(container, totals) {
  clear(container);
  if (!totals) return;
  [
    ["Payments", totals.payments],
    ["Allowed", totals.allow],
    ["Reviewed", totals.review],
    ["Blocked", totals.block],
  ].forEach(([label, value]) => {
    const cell = element("div", "run-total");
    cell.append(element("span", null, label), element("strong", null, Number(value ?? 0).toLocaleString("en-US")));
    container.append(cell);
  });
}

/* The Payment Risk Detail panel. Reuses the exact server-side allowlisted
   projection (`build_projection` / `safe_evidence`) and the fail-closed
   reason contract -- it selects and labels, it never computes. */
export function renderRiskDetail(container, payment) {
  clear(container);
  if (!payment) {
    const empty = element("div", "operations-empty");
    empty.append(
      element("span", "empty-shield", "◇"),
      element("strong", null, "Select a payment"),
      element("p", null, "Choose any row in the feed to see the risk assessment the engine produced for it."),
    );
    container.append(empty);
    return;
  }
  const op = payment.operations;

  const head = element("div", "detail-head");
  const headline = element("div", "detail-headline");
  headline.append(
    element("small", null, "Risk score"),
    element("strong", null, `${riskScore(op.risk_score)} — ${titleCase(op.risk_band)}`),
  );
  head.append(headline, element("span", `decision-badge ${op.decision}`, op.decision));
  container.append(head);
  container.append(element("p", "score-disclaimer", op.risk_score_label || "Risk score — not a guaranteed fraud probability."));
  if (isSaturated(op.risk_score)) {
    container.append(
      element(
        "p",
        "score-disclaimer",
        "1.000 is the top bin of the isotonic calibrator, not a claim of certainty.",
      ),
    );
  }

  const facts = element("dl", "detail-facts");
  [
    ["Device", payment.device_key],
    ["Attempt", `#${payment.attempt} on this device`],
    ["Amount", currency(payment.amount, payment.currency)],
    ["Card", payment.card_alias],
    ["Virtual time", virtualElapsed(payment.virtual_offset_seconds)],
    ["Lifecycle", lifecycleSummary(op)],
  ].forEach(([label, value]) => {
    facts.append(element("dt", null, label), element("dd", null, value));
  });
  container.append(facts);

  const why = element("section", "ops-section");
  why.append(element("h4", null, op.decision === "allow" ? "Signals observed" : "Why this action"));
  renderReasons(why, op.reason_codes, { limit: 5 });
  container.append(why);

  const technical = element("details", "detail-technical");
  technical.append(element("summary", null, "Technical evidence"));
  const signals = element("dl", "signal-grid detail-list");
  let count = 0;
  SAFE_SIGNALS.forEach(([key, label]) => {
    if (!Object.hasOwn(op.evidence || {}, key)) return;
    const item = element("div", "signal-item");
    item.append(element("dt", null, label), element("dd", null, op.evidence[key]));
    signals.append(item);
    count += 1;
  });
  if (count) technical.append(signals);
  else technical.append(element("p", "reason-empty", "No safe causal signals are available for this attempt."));
  const footer = element("div", "ops-footer");
  [
    ["Rule score", String(op.rule_score)],
    ["State", `v${op.state_version}`],
    ["Latency", latency(op.latency_ms)],
    ["Protected ref", op.protected_reference || "—"],
  ].forEach(([label, value]) => {
    const item = element("span");
    item.append(document.createTextNode(`${label} `), element("code", null, value));
    footer.append(item);
  });
  technical.append(footer);
  technical.append(element("p", "detail-note", "Six allowlisted causal signals. The full 44-feature vector never leaves the backend."));
  container.append(technical);
}

/* Sequential risk trajectory for one device. This is the point of the whole
   system: card testing is a sequence, not a single row, and the score has to
   be read across attempts. */
export function renderTrajectory(container, deviceKey, attempts) {
  clear(container);
  if (!attempts?.length) {
    container.append(element("p", "timeline-empty", "Select a payment to see how risk evolved for its device."));
    return;
  }
  container.append(element("p", "trajectory-title", `Risk trajectory · ${deviceKey}`));
  const list = element("div", "trajectory-list");
  attempts.forEach((row) => {
    const op = row.operations;
    const item = element("div", `trajectory-row ${op.decision}`);
    const bar = element("span", "trajectory-bar");
    const fill = element("span", `trajectory-fill ${op.decision}`);
    fill.style.width = `${Math.max(2, Math.min(100, Number(op.risk_score) * 100))}%`;
    bar.append(fill);
    item.append(
      element("span", "trajectory-attempt", `Attempt ${row.attempt}`),
      bar,
      element("span", "trajectory-score", riskScore(op.risk_score)),
      element("span", `trajectory-action ${op.decision}`, op.decision),
    );
    list.append(item);
  });
  container.append(list);

  const firstReview = attempts.find((row) => row.operations.decision !== "allow");
  const firstBlock = attempts.find((row) => row.operations.decision === "block");
  const summary = element("dl", "trajectory-summary");
  const start = attempts[0].virtual_offset_seconds;
  [
    ["Payments scored", String(attempts.length)],
    ["First intervention", firstReview ? `Attempt ${firstReview.attempt}` : "None"],
    ["First block", firstBlock ? `Attempt ${firstBlock.attempt}` : "None"],
    [
      "Virtual time to intervention",
      firstReview ? virtualElapsed(firstReview.virtual_offset_seconds - start) : "—",
    ],
  ].forEach(([label, value]) => {
    summary.append(element("dt", null, label), element("dd", null, value));
  });
  container.append(summary);
}

/* Ground-truth reveal. Rendered only on explicit request, from a separate
   endpoint, strictly after every decision above already exists. */
export function renderTruth(container, payload) {
  clear(container);
  if (!payload) return;
  const table = element("table", "truth-table");
  const head = element("thead");
  const headRow = element("tr");
  ["Device", "Ground truth", "Sentinel", "First review", "First block"].forEach((label) => {
    headRow.append(element("th", null, label));
  });
  head.append(headRow);
  table.append(head);
  const body = element("tbody");
  payload.devices.forEach((device) => {
    const row = element("tr", device.is_attack ? "is-attack" : "is-legitimate");
    let verdict = "No action";
    if (device.is_attack) verdict = device.detected ? "Detected" : "Missed";
    else if (device.detected) verdict = "False positive";
    row.append(
      element("td", null, device.device_key),
      element("td", null, device.scenario_label),
      element("td", `truth-verdict ${verdict.toLowerCase().replace(/\s+/g, "-")}`, verdict),
      element("td", null, device.first_review_attempt ? `Attempt ${device.first_review_attempt}` : "—"),
      element("td", null, device.first_block_attempt ? `Attempt ${device.first_block_attempt}` : "—"),
    );
    body.append(row);
  });
  table.append(body);
  container.append(table);
  container.append(element("p", "detail-note", payload.disclosure));
}

/* Groups a long-horizon replay by virtual day so a scenario that genuinely
   spans days reads as days, instead of collapsing into a flat list that
   implies everything happened in one sitting. */
export function groupByVirtualDay(steps) {
  const groups = [];
  steps.forEach((step) => {
    const day = virtualDay(step.attempt?.elapsed_seconds ?? 0);
    const last = groups.at(-1);
    if (last && last.day === day) last.steps.push(step);
    else groups.push({ day, steps: [step] });
  });
  return groups;
}

/* ────────────────────────────────────────────────────────────────────────
   Frozen evaluation evidence
   ──────────────────────────────────────────────────────────────────────── */

/* A label/value list. `emphasis: true` marks the primary metric in a group so
   review-or-higher recall reads as the headline and block rate reads as the
   conservative subset beneath it, rather than the two competing as peers. */
export function renderMetricList(container, rows) {
  clear(container);
  rows.forEach(({ label, value, emphasis, note }) => {
    const term = element("dt", emphasis ? "is-primary" : null, label);
    const detail = element("dd", emphasis ? "is-primary" : null, value);
    container.append(term, detail);
    if (note) {
      const spacer = element("dt", "metric-note-label");
      container.append(spacer, element("dd", "metric-note", note));
    }
  });
}

/* The baseline comparison. Every number is read from the frozen artifact;
   nothing is computed here. The Sentinel row is marked but not restyled into
   a sales pitch -- a reviewer should be able to read the losing columns
   (count ≥10 and rules ≥5 both have a *lower* false-positive rate) without
   the table hiding them. */
export function renderBaselineTable(container, comparison, options = {}) {
  clear(container);
  if (!comparison?.baselines?.length) {
    container.append(element("p", "reason-empty", "No baseline comparison artifact is loaded."));
    return;
  }
  const wrap = element("div", "table-scroll");
  const table = element("table", "baseline-table");
  const head = element("thead");
  const headRow = element("tr");
  ["Approach", "Attacker recall", "Legitimate devices flagged"].forEach((label, index) => {
    headRow.append(element("th", index ? "is-numeric" : null, label));
  });
  head.append(headRow);
  table.append(head);

  const body = element("tbody");
  const shown = options.only
    ? comparison.baselines.filter((row) => options.only.includes(row.id))
    : comparison.baselines;
  shown.forEach((row) => {
    const tr = element("tr", row.is_sentinel ? "is-sentinel" : null);
    tr.append(
      element("td", null, row.label),
      element("td", "is-numeric", percent(row.attacker_recall, 1)),
      element(
        "td",
        "is-numeric",
        `${row.legitimate_flagged} of ${row.legitimate_devices} · ${percent(row.legitimate_false_positive_rate, 2)}`,
      ),
    );
    body.append(tr);
  });
  table.append(body);
  wrap.append(table);
  container.append(wrap);
}

/* Failure modes, rendered as evidence rather than buried in a footnote.
   Detection rate per attack subtype plus the never-detected count. */
export function renderFailureModes(container, failures) {
  clear(container);
  if (!failures?.by_subtype?.length) return;
  const wrap = element("div", "table-scroll");
  const table = element("table", "baseline-table");
  const head = element("thead");
  const headRow = element("tr");
  ["Attack behaviour", "Review or higher", "Blocked", "Never detected"].forEach((label, index) => {
    headRow.append(element("th", index ? "is-numeric" : null, label));
  });
  head.append(headRow);
  table.append(head);
  const body = element("tbody");
  const weakest = [...failures.by_subtype].sort(
    (a, b) => a.review_or_higher_rate - b.review_or_higher_rate,
  )[0];
  failures.by_subtype.forEach((row) => {
    const tr = element("tr", row.subtype === weakest?.subtype ? "is-weakest" : null);
    tr.append(
      element("td", null, row.label),
      element("td", "is-numeric", percent(row.review_or_higher_rate, 1)),
      element("td", "is-numeric", percent(row.block_rate, 1)),
      element("td", "is-numeric", `${row.never_detected} of ${row.devices}`),
    );
    if (row.subtype === weakest?.subtype) {
      tr.querySelector("td").append(element("span", "weakest-tag", "weakest"));
    }
    body.append(tr);
  });
  table.append(body);
  wrap.append(table);
  container.append(wrap);

  const summary = element("p", "evidence-note");
  const worst = [...failures.by_subtype].sort((a, b) => b.never_detected - a.never_detected)[0];
  summary.textContent =
    `${failures.never_detected} of ${failures.attacker_devices} attacker devices were never detected` +
    (worst && worst.never_detected
      ? ` — ${worst.never_detected} of them ${worst.label.toLowerCase()}.`
      : ".") +
    ` No attacker was detected within the first three attempts (${failures.detected_within_three_attempts} of ${failures.attacker_devices}).`;
  container.append(summary);
}

/* The baseline trade-off chart.

   Form: two measures across seven identities is a scatter, not bars. There is
   exactly one meaningful distinction here -- Sentinel versus the simple
   systems -- so it is encoded as emphasis (filled accent versus hollow muted
   ink), never as seven categorical hues. Seven hues would be decoration, and
   would put a colourblind-safety burden on a chart that does not need it.

   The shaded region is the argument drawn: everything with *both* higher
   recall and lower legitimate impact than Sentinel. It is positioned from the
   artifact's own Sentinel values, so if a future artifact ever produced a
   dominant baseline, that baseline's mark would visibly land inside the box.
   The picture cannot disagree with the table beneath it. */
export function renderBaselineChart(container, comparison) {
  clear(container);
  const rows = comparison?.baselines;
  if (!rows?.length) return;
  const sentinel = rows.find((row) => row.is_sentinel);
  if (!sentinel) return;

  const W = 760;
  const H = 260;
  const PAD = { top: 24, right: 30, bottom: 44, left: 56 };
  const plotW = W - PAD.left - PAD.right;
  const plotH = H - PAD.top - PAD.bottom;
  const maxFp = Math.max(...rows.map((r) => r.legitimate_false_positive_rate), 0.005) * 1.18;
  const x = (fp) => PAD.left + (fp / maxFp) * plotW;
  const minRecall = Math.max(0, Math.min(...rows.map((r) => r.attacker_recall)) - 0.12);
  const y = (recall) => PAD.top + (1 - (recall - minRecall) / (1 - minRecall)) * plotH;

  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("class", "tradeoff-chart");
  svg.setAttribute("role", "img");
  svg.setAttribute(
    "aria-label",
    `Trade-off between attacker recall and legitimate devices affected for ${rows.length} systems. ` +
      `Sentinel reaches ${percent(sentinel.attacker_recall, 1)} recall affecting ` +
      `${sentinel.legitimate_flagged} of ${sentinel.legitimate_devices} legitimate devices. ` +
      "The table below carries every value.",
  );
  const ns = (tag, attrs, text) => {
    const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
    Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, String(value)));
    if (text !== undefined) node.textContent = String(text);
    return node;
  };

  // Recessive gridlines and axis ticks.
  const recallTicks = [minRecall, minRecall + (1 - minRecall) / 2, 1];
  recallTicks.forEach((tick) => {
    svg.append(ns("line", { class: "tc-grid", x1: PAD.left, x2: W - PAD.right, y1: y(tick), y2: y(tick) }));
    svg.append(ns("text", { class: "tc-tick", x: PAD.left - 9, y: y(tick) + 4, "text-anchor": "end" }, percent(tick, 0)));
  });
  const fpTicks = [0, maxFp / 3, (maxFp / 3) * 2, maxFp];
  fpTicks.forEach((tick) => {
    svg.append(ns("text", { class: "tc-tick", x: x(tick), y: H - PAD.bottom + 20, "text-anchor": "middle" }, percent(tick, 1)));
  });
  svg.append(ns("text", { class: "tc-axis", x: PAD.left + plotW / 2, y: H - 8, "text-anchor": "middle" }, "legitimate devices affected"));
  svg.append(ns("text", { class: "tc-axis", x: 12, y: PAD.top + plotH / 2, "text-anchor": "middle", transform: `rotate(-90 12 ${PAD.top + plotH / 2})` }, "attacker recall"));

  // Nothing reaches here: higher recall AND lower legitimate impact.
  const boxX = PAD.left;
  const boxY = PAD.top;
  const boxW = Math.max(0, x(sentinel.legitimate_false_positive_rate) - PAD.left);
  const boxH = Math.max(0, y(sentinel.attacker_recall) - PAD.top);
  if (boxW > 4 && boxH > 8) {
    svg.append(ns("rect", { class: "tc-dominance", x: boxX, y: boxY, width: boxW, height: boxH, rx: 4 }));
    /* The region is a narrow sliver whenever Sentinel sits close to the axes,
       which is the good case. Put the label beside it rather than inside. */
    const inside = boxW > 190;
    svg.append(
      ns(
        "text",
        {
          class: "tc-dominance-label",
          x: inside ? boxX + 10 : boxX + boxW + 10,
          y: boxY + 13,
          "text-anchor": "start",
        },
        "no system reaches here",
      ),
    );
  }

  /* Points cluster: count >=10 and rules >=5 land almost on top of each
     other. Place each label, then nudge it vertically until it clears the
     ones already placed, so no pair overlaps. */
  const placed = [];
  const clearOf = (px, py) => {
    for (let step = 0; step < 8; step += 1) {
      const offset = step === 0 ? 0 : (step % 2 ? 1 : -1) * Math.ceil(step / 2) * 15;
      const candidate = py + offset;
      if (!placed.some((p) => Math.abs(p.y - candidate) < 13 && Math.abs(p.x - px) < 132)) {
        placed.push({ x: px, y: candidate });
        return candidate;
      }
    }
    return py;
  };

  svg.append(
    ns(
      "text",
      { class: "tc-direction", x: W - PAD.right, y: PAD.top + 2, "text-anchor": "end" },
      "◤ better",
    ),
  );

  rows.forEach((row) => {
    const cx = x(row.legitimate_false_positive_rate);
    const cy = y(row.attacker_recall);
    const mark = ns("circle", {
      class: row.is_sentinel ? "tc-mark is-sentinel" : "tc-mark",
      cx,
      cy,
      r: row.is_sentinel ? 7 : 5,
    });
    mark.append(
      ns("title", {}, `${row.label} — ${percent(row.attacker_recall, 1)} recall, ${row.legitimate_flagged} of ${row.legitimate_devices} legitimate devices affected`),
    );
    svg.append(mark);
    const flip = cx > PAD.left + plotW * 0.62;
    const labelX = flip ? cx - 12 : cx + 12;
    const labelY = clearOf(labelX, cy + 4);
    if (Math.abs(labelY - (cy + 4)) > 6) {
      svg.append(ns("line", { class: "tc-leader", x1: cx, y1: cy, x2: labelX, y2: labelY - 4 }));
    }
    svg.append(
      ns(
        "text",
        {
          class: row.is_sentinel ? "tc-label is-sentinel" : "tc-label",
          x: labelX,
          y: labelY,
          "text-anchor": flip ? "end" : "start",
        },
        row.is_sentinel ? "Sentinel" : row.label.replace(" requests", "").replace(" points", ""),
      ),
    );
  });

  container.append(svg);
}
