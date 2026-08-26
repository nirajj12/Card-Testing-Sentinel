import {
  clockTime,
  explainReason,
  latency,
  riskScore,
  shortId,
  titleCase,
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
  reasons.forEach((code) => {
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
  band.append(element("small", null, `${op.rule_score} rule point${op.rule_score === 1 ? "" : "s"}`), element("strong", null, `${titleCase(op.risk_band)} band`));
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
  renderReasons(reasonSection, op.reason_codes, { heading: reasonsHeading(op.decision) });
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
  if (action === "block") return "Authorization suppressed. Bank not contacted. No outcome event created.";
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
    container.append(element("p", "timeline-empty", "Start a scenario to create the first causally scored attempt."));
    return;
  }
  steps.forEach((step, index) => {
    const op = step.operations;
    const attempt = step.attempt;
    const row = element("article", "transaction-row");
    if (options.currentIndex === index) row.classList.add("is-current");
    const primary = element("div", "timeline-primary");
    primary.append(element("strong", null, `Attempt ${attempt.attempt}`), element("span", null, attempt.timestamp ? clockTime(attempt.timestamp) : `+${attempt.elapsed_seconds || 0}s`));
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
    container.append(row);
  });
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
