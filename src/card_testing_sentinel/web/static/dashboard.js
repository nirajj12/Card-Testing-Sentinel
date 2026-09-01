import { api, ApiError } from "./api-client.js";
import { currency, latency, percent, shortId, titleCase } from "./formatters.js";
import { ReplayController } from "./replay-controller.js";

const byId = (id) => document.getElementById(id);
const reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
const stageDelay = reducedMotion ? 0 : 180;

const nodes = {
  statusButton: byId("system-status-button"),
  statusLabel: byId("system-status-label"),
  statusPopover: byId("system-popover"),
  message: byId("global-message"),
  pay: byId("customer-pay"),
  payLabel: document.querySelector("[data-pay-label]"),
  customerMessage: byId("customer-message"),
  panel: byId("protection-panel"),
  idle: byId("protection-idle"),
  progress: byId("decision-progress"),
  result: byId("decision-result"),
  monitoring: byId("monitoring-label"),
  badge: byId("decision-badge"),
  latency: byId("decision-latency"),
  score: byId("risk-score"),
  band: byId("risk-band"),
  fill: byId("risk-fill"),
  title: byId("decision-title"),
  copy: byId("decision-copy"),
  orderCreated: byId("order-created"),
  checkoutOpened: byId("checkout-opened"),
  orderIdRow: byId("order-id-row"),
  orderId: byId("razorpay-order-id"),
  reasons: byId("decision-reasons"),
  email: byId("checkout-email"),
  contact: byId("checkout-contact"),
  scenarios: byId("scenario-cards"),
  startDemo: byId("start-demo"),
  exitDemo: byId("exit-demo"),
  previous: byId("previous-step"),
  play: byId("play-demo"),
  next: byId("next-step"),
  attemptCounter: byId("attempt-counter"),
  attemptTotal: byId("attempt-total"),
  feed: byId("attempt-feed"),
  drawer: byId("attempt-drawer"),
  drawerBody: byId("drawer-body"),
  evidenceStatus: byId("evidence-status"),
  evidenceHeadline: byId("evidence-headline"),
  detectionChart: byId("detection-chart"),
  scenarioChart: byId("scenario-chart"),
};

const state = {
  mode: "razorpay",
  selectedScenario: "normal_customer",
  demoId: null,
  demoComplete: false,
  system: null,
  attempts: [],
  totalAttempts: null,
  replay: null,
};

const scenarioLabels = {
  normal_customer: "Normal Purchase",
  normal_bad_luck: "Genuine Retry",
  burst_attacker: "Rapid Attack",
  patient_attacker: "Patient Attack",
};

const evidenceLabels = {
  requests_5m: "Requests in 5 minutes",
  recent_failures_24h: "Previous verified failures",
  decline_streak: "Verified decline streak",
  sessions_24h: "Sessions in 24 hours",
  ip_changes_24h: "IP changes in 24 hours",
  successful_checkouts: "Successful checkouts",
};

const reasonLabels = {
  elevated_model_risk: "Elevated behavioral risk",
  repeated_verified_failures: "Repeated verified failures",
  verified_decline_streak: "Verified decline streak",
  multi_session_persistence: "Multiple recent sessions",
  ip_rotation_evidence: "Recent IP changes",
  sustained_request_burst: "High recent request activity",
  rapid_retry_after_decline: "Rapid retries after declines",
  campaign_tolerance_applied: "Campaign tolerance applied",
  degraded_rules_only: "Rules-only fallback active",
};

function textNode(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = String(text);
  return node;
}

function sleep(milliseconds) {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

function showMessage(message, type = "info") {
  nodes.message.textContent = message;
  nodes.message.className = `global-message ${type === "error" ? "error" : ""}`;
  nodes.message.hidden = !message;
  if (message) window.setTimeout(() => { nodes.message.hidden = true; }, 5000);
}

function friendlyError(error) {
  if (error instanceof ApiError) return error.message;
  return "The operation could not be completed.";
}

function setView(view) {
  document.querySelectorAll(".app-view").forEach((node) => {
    const active = node.id === `view-${view}`;
    node.hidden = !active;
    node.classList.toggle("is-active", active);
  });
  document.querySelectorAll(".nav-tab").forEach((tab) => {
    const active = tab.dataset.viewTarget === view;
    tab.classList.toggle("is-active", active);
    tab.setAttribute("aria-selected", String(active));
  });
  if (view === "evidence") loadEvidence();
  window.scrollTo({ top: 0, behavior: reducedMotion ? "auto" : "smooth" });
}

function resetProtection() {
  nodes.panel.dataset.decision = "idle";
  nodes.idle.hidden = false;
  nodes.progress.hidden = true;
  nodes.result.hidden = true;
  nodes.monitoring.textContent = "Monitoring";
  nodes.orderIdRow.hidden = true;
  nodes.reasons.replaceChildren();
  document.querySelectorAll("[data-progress]").forEach((item) => item.classList.remove("is-complete"));
}

async function beginDecision() {
  nodes.idle.hidden = true;
  nodes.result.hidden = true;
  nodes.progress.hidden = false;
  nodes.monitoring.textContent = "Evaluating";
  const received = nodes.progress.querySelector('[data-progress="received"]');
  received.classList.add("is-complete");
  await sleep(stageDelay);
}

async function completeDecisionProgress() {
  for (const key of ["history", "policy"]) {
    nodes.progress.querySelector(`[data-progress="${key}"]`).classList.add("is-complete");
    await sleep(stageDelay);
  }
}

function decisionPresentation(decision) {
  if (decision === "allow") return {
    badge: "ALLOW",
    title: "Razorpay order creation permitted",
    copy: "Sentinel completed the pre-authorization check.",
    customer: "Protection check complete. Preparing secure checkout…",
  };
  if (decision === "review") return {
    badge: "REVIEW",
    title: "Additional verification recommended",
    copy: "Merchant intervention recommended. No automatic review action is configured.",
    customer: "We couldn't start this payment right now. Please wait and try again.",
  };
  return {
    badge: "TEMPORARILY BLOCKED",
    title: "Order creation suppressed",
    copy: "This attempt stopped before Razorpay Checkout. A later request can be scored again.",
    customer: "We couldn't start this payment right now. Please wait and try again.",
  };
}

function renderDecision(operation, { simulation = false } = {}) {
  const decision = operation.decision;
  const view = decisionPresentation(decision);
  const numeric = Number(operation.risk_score);
  const score = Number.isFinite(numeric) ? Math.round(numeric * 100) : null;
  nodes.panel.dataset.decision = decision;
  nodes.progress.hidden = true;
  nodes.result.hidden = false;
  nodes.monitoring.textContent = simulation ? "Simulation" : "Decision complete";
  nodes.badge.textContent = view.badge;
  nodes.latency.textContent = Number.isFinite(Number(operation.latency_ms)) ? latency(operation.latency_ms) : "Stored decision";
  nodes.score.textContent = score === null ? "—" : String(score).padStart(2, "0");
  nodes.band.textContent = score === null ? "Rules-only decision" : `${titleCase(operation.risk_band || "risk")} risk`;
  nodes.fill.style.width = `${score || 0}%`;
  nodes.title.textContent = view.title;
  nodes.copy.textContent = simulation ? `${view.copy} Synthetic replay — Razorpay Checkout will not open.` : view.copy;
  nodes.customerMessage.textContent = simulation
    ? (decision === "allow" ? "Synthetic attempt sent for authorization." : view.customer)
    : view.customer;
  nodes.orderCreated.textContent = decision === "allow" && !simulation ? "PENDING" : "NO";
  nodes.checkoutOpened.textContent = "NO";
  nodes.orderIdRow.hidden = true;
  nodes.reasons.replaceChildren();
  (operation.reason_codes || []).slice(0, 3).forEach((reason) => {
    nodes.reasons.append(textNode("span", "", reasonLabels[reason] || titleCase(reason)));
  });
}

function normalizeOperation(response) {
  return {
    decision: response.decision,
    risk_score: response.risk_score,
    risk_band: response.risk_score == null ? "unavailable" : response.risk_score < .25 ? "low" : response.risk_score < .5 ? "elevated" : response.risk_score < .75 ? "high" : "very high",
    reason_codes: response.reason_codes || [],
    latency_ms: response.latency_ms,
    evidence: response.evidence || {},
    protected_reference: response.protected_reference || shortId(response.request_id || "", 12),
    state_version: response.device_state_version,
  };
}

function nextIdentity() {
  let device = sessionStorage.getItem("sentinel_demo_device");
  let session = sessionStorage.getItem("sentinel_demo_session");
  if (!device || !session) {
    const suffix = crypto.randomUUID().replaceAll("-", "").slice(0, 12);
    device = `checkout-device-${suffix}`;
    session = `checkout-session-${suffix}`;
    sessionStorage.setItem("sentinel_demo_device", device);
    sessionStorage.setItem("sentinel_demo_session", session);
  }
  const sequence = Number(sessionStorage.getItem("sentinel_demo_sequence") || "0") + 1;
  sessionStorage.setItem("sentinel_demo_sequence", String(sequence));
  return { device, session, sequence };
}

async function realPayment() {
  const email = nodes.email.value.trim();
  const contact = nodes.contact.value.trim();
  if (!email || !nodes.email.checkValidity() || !contact) {
    showMessage("Enter a valid email and mobile number before continuing.", "error");
    return;
  }
  const identity = nextIdentity();
  const run = crypto.randomUUID().replaceAll("-", "").slice(0, 16);
  const requestId = `checkout-request-${run}`;
  const body = {
    request_id: requestId,
    event_id: `checkout-precheck-${run}`,
    merchant_id: "northstar-test-merchant",
    customer_id: email,
    device_id: identity.device,
    session_id: identity.session,
    ip_reference: "browser-test-reference",
    amount: 2499.0,
    currency: "INR",
    campaign_active: false,
    timestamp: new Date().toISOString(),
    event_sequence: identity.sequence,
  };
  nodes.pay.disabled = true;
  nodes.payLabel.textContent = "Checking payment…";
  resetProtection();
  await beginDecision();
  try {
    const { data } = await api.precheck(body);
    await completeDecisionProgress();
    const operation = normalizeOperation(data);
    renderDecision(operation);
    addAttempt({
      attempt: state.attempts.length + 1,
      amount: body.amount,
      currency: body.currency,
      timestamp: body.timestamp,
      operations: operation,
      request_id: requestId,
    });
    if (data.decision !== "allow") return;
    const order = await api.razorpayOrder({
      sentinel_request_id: requestId,
      device_id: identity.device,
      session_id: identity.session,
    });
    nodes.orderCreated.textContent = "YES";
    nodes.orderIdRow.hidden = false;
    nodes.orderId.textContent = order.razorpay_order_id;
    await openRazorpayCheckout({ order, requestId, identity, email, contact });
  } catch (error) {
    nodes.customerMessage.textContent = "We couldn't start this payment right now. Please try again.";
    showMessage(friendlyError(error), "error");
    if (!nodes.result.hidden) {
      nodes.copy.textContent = "Sentinel allowed the request, but Razorpay order creation could not complete safely.";
      nodes.orderCreated.textContent = "NO";
      nodes.checkoutOpened.textContent = "NO";
    } else {
      resetProtection();
    }
  } finally {
    nodes.pay.disabled = false;
    nodes.payLabel.textContent = state.mode === "demo" ? "Run next synthetic attempt" : "Pay securely with Razorpay";
  }
}

async function openRazorpayCheckout({ order, requestId, identity, email, contact }) {
  if (!window.Razorpay) throw new Error("Razorpay Checkout could not be loaded.");
  const checkout = new window.Razorpay({
    key: order.key_id,
    amount: order.amount,
    currency: order.currency,
    name: "Northstar Store",
    description: "Northstar Air · Test purchase",
    order_id: order.razorpay_order_id,
    prefill: { email, contact },
    theme: { color: "#2b5df5" },
    handler: async (payment) => {
      nodes.customerMessage.textContent = "Verifying payment securely…";
      try {
        await api.verifyRazorpayPayment({
          sentinel_request_id: requestId,
          device_id: identity.device,
          session_id: identity.session,
          razorpay_order_id: payment.razorpay_order_id,
          razorpay_payment_id: payment.razorpay_payment_id,
          razorpay_signature: payment.razorpay_signature,
        });
        nodes.customerMessage.textContent = "Payment verified. Thank you.";
        nodes.copy.textContent = "Razorpay signature verified server-side. The verified outcome is now part of future Sentinel history.";
        nodes.checkoutOpened.textContent = "YES · VERIFIED";
        showMessage("Test payment verified and recorded in Sentinel history.");
      } catch (error) {
        nodes.customerMessage.textContent = "Payment verification failed. The order was not confirmed.";
        showMessage(friendlyError(error), "error");
      }
    },
    modal: {
      ondismiss: () => {
        nodes.customerMessage.textContent = "Checkout closed. No verified outcome was recorded.";
      },
    },
  });
  checkout.on("payment.failed", () => {
    nodes.customerMessage.textContent = "Payment was not completed. No success was recorded.";
  });
  checkout.open();
  nodes.checkoutOpened.textContent = "YES";
  nodes.customerMessage.textContent = "Secure Razorpay Test Checkout opened.";
}

function renderScenarioButtons(items) {
  nodes.scenarios.replaceChildren();
  Object.entries(scenarioLabels).forEach(([id, label]) => {
    if (!items.some((item) => item.id === id)) return;
    const button = textNode("button", `scenario-pill ${state.selectedScenario === id ? "is-selected" : ""}`, label);
    button.type = "button";
    button.setAttribute("role", "radio");
    button.setAttribute("aria-checked", String(state.selectedScenario === id));
    button.addEventListener("click", () => {
      state.selectedScenario = id;
      renderScenarioButtons(items);
    });
    nodes.scenarios.append(button);
  });
  const unavailable = textNode("button", "scenario-pill", "Model Unavailable");
  unavailable.type = "button";
  const degraded = state.system?.model_status === "degraded_rules_only";
  unavailable.disabled = !degraded;
  unavailable.title = degraded ? "The runtime is using its real rules-only fallback." : "Available only when the runtime actually reports degraded mode.";
  nodes.scenarios.append(unavailable);
}

async function startDemo() {
  try {
    const started = await api.demoStart(state.selectedScenario);
    state.mode = "demo";
    state.demoId = started.demo_id;
    state.demoComplete = false;
    state.totalAttempts = started.total_attempts;
    state.attempts = [];
    state.replay.reset();
    nodes.feed.replaceChildren(textNode("p", "empty-row", "Submit the first synthetic attempt to begin."));
    nodes.attemptCounter.textContent = "0";
    nodes.attemptTotal.textContent = String(started.total_attempts);
    nodes.next.disabled = false;
    nodes.play.disabled = false;
    nodes.previous.disabled = true;
    nodes.exitDemo.hidden = false;
    nodes.payLabel.textContent = "Run next synthetic attempt";
    nodes.customerMessage.textContent = `${scenarioLabels[state.selectedScenario]} ready. No expected decision is preloaded.`;
    resetProtection();
  } catch (error) {
    showMessage(friendlyError(error), "error");
  }
}

async function nextDemoAttempt() {
  if (!state.demoId || state.demoComplete) return false;
  if (state.replay.nextRecorded()) return true;
  nodes.pay.disabled = true;
  resetProtection();
  await beginDecision();
  try {
    const step = await api.demoStep(state.demoId);
    if (!step.operations) {
      state.demoComplete = true;
      return false;
    }
    await completeDecisionProgress();
    const item = { ...step.attempt, operations: step.operations, timeline: step.timeline, request_id: step.operations.protected_reference };
    state.replay.push(item);
    addAttempt(item);
    state.demoComplete = Boolean(step.complete);
    nodes.next.disabled = state.demoComplete;
    return !state.demoComplete;
  } catch (error) {
    showMessage(friendlyError(error), "error");
    return false;
  } finally {
    nodes.pay.disabled = false;
  }
}

function exitDemo() {
  state.replay.pause();
  state.mode = "razorpay";
  state.demoId = null;
  state.demoComplete = false;
  nodes.exitDemo.hidden = true;
  nodes.next.disabled = true;
  nodes.play.disabled = true;
  nodes.previous.disabled = true;
  nodes.attemptCounter.textContent = "0";
  nodes.attemptTotal.textContent = "—";
  nodes.payLabel.textContent = "Pay securely with Razorpay";
  nodes.customerMessage.textContent = "Ready to pay.";
  resetProtection();
}

function replayChanged(item, position, length) {
  nodes.attemptCounter.textContent = item ? String(item.attempt) : "0";
  nodes.previous.disabled = position <= 0;
  if (item) renderDecision(item.operations, { simulation: true });
  nodes.next.disabled = state.demoComplete && position >= length - 1;
}

function addAttempt(item) {
  state.attempts.push(item);
  if (nodes.feed.querySelector(".empty-row")) nodes.feed.replaceChildren();
  const operation = item.operations;
  const row = textNode("button", "attempt-row");
  row.type = "button";
  row.append(
    textNode("span", "", `#${item.attempt || state.attempts.length}`),
    textNode("span", "", currency(item.amount, item.currency || "INR")),
    textNode("span", "mono", operation.protected_reference || shortId(item.request_id || "", 12)),
    textNode("span", "", operation.risk_score == null ? "—" : String(Math.round(Number(operation.risk_score) * 100))),
    textNode("span", `decision-mini ${operation.decision}`, operation.decision === "block" ? "BLOCKED" : operation.decision.toUpperCase()),
  );
  row.addEventListener("click", () => openDrawer(item));
  nodes.feed.prepend(row);
}

function openDrawer(item) {
  const op = item.operations;
  nodes.drawerBody.replaceChildren();
  const summary = textNode("div", "drawer-summary");
  [["Decision", op.decision === "block" ? "Temporary block" : titleCase(op.decision)], ["Risk", op.risk_score == null ? "Unavailable" : `${Math.round(Number(op.risk_score) * 100)} / 100`]].forEach(([label, value]) => {
    const card = textNode("div", "drawer-stat");
    card.append(textNode("span", "", label), textNode("strong", "", value));
    summary.append(card);
  });
  nodes.drawerBody.append(summary);
  const evidenceSection = textNode("section", "drawer-section");
  evidenceSection.append(textNode("h3", "", "Behavior at decision time"));
  const evidence = textNode("dl", "evidence-list");
  const entries = Object.entries(op.evidence || {}).slice(0, 6);
  if (!entries.length) {
    evidenceSection.append(textNode("p", "customer-message", "No safe evidence snapshot is available for this attempt."));
  } else {
    entries.forEach(([key, value]) => {
      const row = textNode("div", "");
      row.append(textNode("dt", "", evidenceLabels[key] || titleCase(key)), textNode("dd", "", value));
      evidence.append(row);
    });
    evidenceSection.append(evidence);
  }
  nodes.drawerBody.append(evidenceSection);
  const action = textNode("section", "drawer-section");
  action.append(textNode("h3", "", "Action"), textNode("p", "audit-code", op.decision === "block" ? "Razorpay order creation suppressed" : op.decision === "review" ? "Merchant intervention recommended" : "Eligible for Razorpay order creation"));
  nodes.drawerBody.append(action);
  const audit = textNode("section", "drawer-section");
  audit.append(textNode("h3", "", "Audit"), textNode("p", "audit-code", `${op.protected_reference || item.request_id || "protected reference unavailable"}\n${item.timestamp || "timestamp unavailable"}`));
  nodes.drawerBody.append(audit);
  nodes.drawer.hidden = false;
  document.body.style.overflow = "hidden";
}

function closeDrawer() {
  nodes.drawer.hidden = true;
  document.body.style.overflow = "";
}

let evidenceLoaded = false;
async function loadEvidence() {
  if (evidenceLoaded) return;
  try {
    const result = await api.blindMetrics();
    if (result.status !== "available") throw new Error(result.reason || "Evaluation is unavailable");
    evidenceLoaded = true;
    nodes.evidenceStatus.textContent = `${result.label} · ${result.blind_version} · ${result.active_device_counts.attack} active attack devices · ${result.active_device_counts.legitimate} legitimate devices`;
    const metrics = [
      ["Attack intervention", result.headline.attack_intervention_rate, "Reviewed or temporarily blocked"],
      ["Attack temporary blocks", result.headline.attack_block_rate, "Reached the block action"],
      ["Legitimate intervention", result.headline.legitimate_intervention_rate, "Customer-friction cost"],
      ["Legitimate blocks", result.headline.legitimate_block_rate, "Highest-cost false positives"],
    ];
    nodes.evidenceHeadline.replaceChildren();
    metrics.forEach(([label, value, note]) => {
      const card = textNode("article", "metric-card");
      card.append(textNode("strong", "", percent(value)), textNode("span", "", label), textNode("small", "", note));
      nodes.evidenceHeadline.append(card);
    });
    renderDetectionChart(result.detection_by_attempt);
    renderScenarioChart(result.scenario_metrics);
  } catch (error) {
    nodes.evidenceStatus.textContent = friendlyError(error);
    nodes.evidenceStatus.classList.add("error");
  }
}

function chartRow(label, value, population = "attack") {
  const row = textNode("div", `chart-row ${population === "legitimate" ? "legitimate" : ""}`);
  const track = textNode("div", "chart-track");
  const fill = textNode("i", "");
  fill.style.width = `${Math.max(0, Math.min(1, Number(value))) * 100}%`;
  track.append(fill);
  row.append(textNode("span", "", label), track, textNode("strong", "", percent(value, 0)));
  return row;
}

function renderDetectionChart(values) {
  nodes.detectionChart.replaceChildren();
  Object.entries(values).forEach(([attempt, value]) => nodes.detectionChart.append(chartRow(`By attempt ${attempt}`, value)));
}

function renderScenarioChart(values) {
  nodes.scenarioChart.replaceChildren();
  const attacks = values.filter((row) => row.population === "attack").sort((a, b) => b.intervention_rate - a.intervention_rate).slice(0, 5);
  const legitimate = values.filter((row) => row.population === "legitimate").sort((a, b) => b.intervention_rate - a.intervention_rate).slice(0, 3);
  [...attacks, ...legitimate].forEach((row) => nodes.scenarioChart.append(chartRow(titleCase(row.scenario), row.intervention_rate, row.population)));
}

async function loadSystem() {
  try {
    const system = await api.system();
    state.system = system;
    nodes.statusButton.classList.toggle("is-ready", Boolean(system.ready));
    nodes.statusButton.classList.toggle("is-error", !system.ready);
    nodes.statusLabel.textContent = system.ready ? "System healthy" : "Not ready";
    byId("status-model").textContent = system.model_status === "ready" ? "Ready" : "Rules-only fallback";
    byId("status-policy").textContent = system.policy_stage ? "Ready" : "Unavailable";
    byId("status-store").textContent = system.database?.integrity === "ok" || system.database?.type === "memory" ? "Healthy" : "Check required";
    byId("status-razorpay").textContent = system.razorpay?.configured ? "Test Mode ready" : "Not configured";
    const scenarios = await api.demoScenarios();
    renderScenarioButtons(scenarios.items || []);
  } catch (error) {
    nodes.statusButton.classList.add("is-error");
    nodes.statusLabel.textContent = "Connection failed";
    showMessage(friendlyError(error), "error");
  }
}

function bind() {
  document.querySelectorAll("[data-view-target]").forEach((button) => button.addEventListener("click", () => setView(button.dataset.viewTarget)));
  nodes.statusButton.addEventListener("click", () => {
    nodes.statusPopover.hidden = !nodes.statusPopover.hidden;
    nodes.statusButton.setAttribute("aria-expanded", String(!nodes.statusPopover.hidden));
  });
  document.addEventListener("click", (event) => {
    if (!nodes.statusPopover.hidden && !nodes.statusPopover.contains(event.target) && !nodes.statusButton.contains(event.target)) {
      nodes.statusPopover.hidden = true;
      nodes.statusButton.setAttribute("aria-expanded", "false");
    }
  });
  nodes.pay.addEventListener("click", () => state.mode === "demo" ? nextDemoAttempt() : realPayment());
  nodes.startDemo.addEventListener("click", startDemo);
  nodes.exitDemo.addEventListener("click", exitDemo);
  nodes.next.addEventListener("click", nextDemoAttempt);
  nodes.previous.addEventListener("click", () => state.replay.previous());
  nodes.play.addEventListener("click", () => {
    if (state.replay.playing) {
      state.replay.pause();
      nodes.play.textContent = "Play";
      return;
    }
    nodes.play.textContent = "Pause";
    state.replay.play(nextDemoAttempt, () => { nodes.play.textContent = "Play"; });
  });
  document.querySelectorAll("[data-close-drawer]").forEach((node) => node.addEventListener("click", closeDrawer));
  document.addEventListener("keydown", (event) => { if (event.key === "Escape") closeDrawer(); });
  document.querySelectorAll("[data-flow-branch]").forEach((node) => {
    const flow = byId("sentinel-flow");
    const activate = () => { flow.dataset.activeBranch = node.dataset.flowBranch; };
    const clear = () => { flow.dataset.activeBranch = "none"; };
    node.addEventListener("mouseenter", activate);
    node.addEventListener("focus", activate);
    node.addEventListener("mouseleave", clear);
    node.addEventListener("blur", clear);
  });
}

state.replay = new ReplayController(replayChanged);
bind();
resetProtection();
loadSystem();
