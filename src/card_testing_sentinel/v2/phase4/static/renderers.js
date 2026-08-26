import { latency, percent, riskScore, timestamp, titleCase } from "./formatters.js";

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

export function clear(node) {
  node.replaceChildren();
}

export function renderMetrics(container, metrics, runtime) {
  clear(container);
  const policy = metrics.operational_policy;
  const latencyValues = runtime.per_request_scoring_latency;
  const cards = [
    ["Attacker review", percent(policy.attacker_review_or_higher.rate, 2), `${policy.attacker_review_or_higher.numerator}/${policy.attacker_review_or_higher.denominator} devices`],
    ["Attacker block", percent(policy.attacker_block.rate, 2), `${policy.attacker_block.numerator}/${policy.attacker_block.denominator} devices`],
    ["Legitimate review", `${policy.legitimate_review_or_higher}/1,700`, "Within all subgroup budgets"],
    ["Legitimate block", `${policy.legitimate_blocks}/1,700`, "No blind legitimate blocks"],
    ["Never detected", `${policy.never_detected_attackers}/300`, "All attackers remain in denominator"],
    ["Scoring p95", latency(latencyValues.p95), `p50 ${latency(latencyValues.p50)} · p99 ${latency(latencyValues.p99)}`],
  ];
  cards.forEach(([label, value, detail]) => {
    const card = element("article", "metric-card");
    card.append(element("p", "metric-label", label), element("p", "metric-value", value), element("p", "metric-detail", detail));
    container.append(card);
  });
}

export function renderBars(container, rows) {
  clear(container);
  const maximum = Math.max(...rows.map((row) => row.value), 1);
  rows.forEach((row) => {
    const wrapper = element("div", "bar-row");
    const track = element("div", "bar-track");
    const fill = element("div", `bar-fill ${row.className || ""}`);
    fill.style.width = `${Math.max((row.value / maximum) * 100, 1)}%`;
    track.append(fill);
    wrapper.append(element("span", "", row.label), track, element("strong", "", row.display || String(row.value)));
    container.append(wrapper);
  });
}

export function renderDecision(container, item) {
  clear(container);
  if (!item?.decision) {
    container.className = "decision-empty";
    container.textContent = "Start a scenario";
    return;
  }
  container.className = "decision-result";
  const decision = item.decision;
  container.append(
    element("span", `decision-badge ${decision.decision}`, `${titleCase(decision.decision)} decision`),
    element("span", "risk-value", riskScore(decision.risk_score)),
    element("span", "muted", `risk score · rule ${decision.rule_score}`),
    element("span", "muted", `state v${decision.device_state_version} · ${latency(decision.latency_ms)}`),
  );
}

export function renderDetails(container, values) {
  clear(container);
  Object.entries(values).forEach(([label, value]) => {
    container.append(element("dt", "", label), element("dd", "", value ?? "—"));
  });
}

export function renderReasons(container, reasons) {
  clear(container);
  if (!reasons?.length) {
    container.append(element("p", "muted", "No elevated policy evidence."));
    return;
  }
  reasons.forEach((reason) => container.append(element("span", "reason-code", titleCase(reason))));
}

export function renderTimeline(container, items, options = {}) {
  clear(container);
  if (!items?.length) {
    container.append(element("p", "empty-state", options.empty || "No timeline events."));
    return;
  }
  let authorizationAttempt = 0;
  items.forEach((item) => {
    if (item.event_type && item.event_type !== "authorization_request" && !item.action) return;
    authorizationAttempt += 1;
    const action = item.action || item.decision || "allow";
    const card = element("article", `timeline-item ${action}`);
    card.append(
      element("span", "timeline-index", `Attempt ${item.request_index || authorizationAttempt}`),
      element("p", "timeline-action", titleCase(action)),
      element("p", "timeline-score", riskScore(item.calibrated_probability ?? item.risk_score)),
      element("span", "muted", item.timestamp ? timestamp(item.timestamp) : `State v${item.state_version || "—"}`),
    );
    container.append(card);
  });
}

export function renderDeviceList(container, items, onSelect) {
  clear(container);
  if (!items.length) {
    container.append(element("p", "empty-state", "No devices match these filters."));
    return;
  }
  items.forEach((item) => {
    const button = element("button", "device-row");
    const result = item.blocked ? "Blocked" : item.review_or_higher ? "Reviewed" : "Allowed";
    button.append(
      element("strong", "", item.device_id),
      element("span", "", `${titleCase(item.attack_subtype || item.scenario_tag)} · ${result}`),
    );
    button.addEventListener("click", () => onSelect(item.device_id));
    container.append(button);
  });
}

export function renderSystem(container, system) {
  clear(container);
  const cards = [
    ["Application", system.ready ? "Ready" : "Not ready", `Model ${system.model_version}`],
    ["Frozen policy", system.policy_version, system.policy_sha256],
    ["Feature contract", `${system.feature_count} server-side features`, system.feature_contract_sha256],
    ["Phase 3 manifest", "Verified", system.phase3_final_manifest_sha256],
    ["Runtime database", system.database.type, `WAL ${system.database.wal_mode ? "enabled" : "disabled"} · ${system.database.requests} requests`],
    ["Artifact lifecycle", `${system.artifact_load_count} startup load`, `${system.concurrency}; prototype only`],
  ];
  cards.forEach(([label, value, detail]) => {
    const card = element("article", "system-card");
    card.append(element("p", "eyebrow", label), element("strong", "", value), element("code", "", detail));
    container.append(card);
  });
}
