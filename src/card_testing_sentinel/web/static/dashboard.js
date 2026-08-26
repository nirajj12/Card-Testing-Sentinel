import { api } from "./api-client.js";
import { currency, customerState, percent } from "./formatters.js";
import { ReplayController } from "./replay-controller.js";
import {
  clear,
  element,
  renderAuthoritativeTimeline,
  renderOperations,
} from "./renderers.js";

const byId = (id) => document.getElementById(id);
const messageNode = byId("global-message");

let demoId = null;
let demoComplete = false;
let demoTotalAttempts = null;
let requestPending = false;

function setMessage(text, kind = "error") {
  if (!text) {
    messageNode.className = "message is-hidden";
    messageNode.textContent = "";
    return;
  }
  messageNode.textContent = text;
  messageNode.className = `message${kind === "loading" ? " is-loading" : ""}${kind === "success" ? " is-success" : ""}`;
}

function showError(error) {
  setMessage(error?.message || "The request could not be completed.");
}

function setCustomerPresentation(item, { processing = false } = {}) {
  const status = byId("customer-status");
  const statusText = status.querySelector("[data-customer-status]");
  const statusIcon = status.querySelector(".customer-status-icon");
  const pay = byId("customer-pay");
  const payLabel = pay.querySelector("[data-pay-label]");
  status.className = "customer-status neutral";
  pay.classList.toggle("is-processing", processing);

  if (processing) {
    statusText.textContent = "Securely checking this payment request…";
    statusIcon.textContent = "•";
    payLabel.textContent = "Processing";
    return;
  }

  const operations = item?.operations || null;
  const message = customerState(operations);
  statusText.textContent = message;
  payLabel.textContent = demoComplete ? "Scenario complete" : "Pay next attempt";

  if (!operations) {
    statusText.textContent = demoId
      ? "Ready for the next synthetic payment."
      : "Start a scenario to prepare a synthetic payment.";
    statusIcon.textContent = "•";
  } else if (operations.decision === "block") {
    status.classList.add("blocked");
    statusIcon.textContent = "×";
  } else if (operations.decision === "review") {
    status.classList.add("review");
    statusIcon.textContent = "!";
  } else if (operations.outcome_status === "approved") {
    status.classList.add("approved");
    statusIcon.textContent = "✓";
  } else if (operations.outcome_status === "declined") {
    status.classList.add("declined");
    statusIcon.textContent = "×";
  } else {
    statusIcon.textContent = "✓";
  }
}

const demoController = new ReplayController((item, position, total) => {
  paintDemoStep(item, position, total);
});

function paintDemoStep(item, position, total) {
  if (item?.attempt) {
    byId("customer-amount").textContent = currency(item.attempt.amount, item.attempt.currency);
    byId("customer-card").textContent = item.attempt.card_alias || "Synthetic card alias";
    byId("customer-order").textContent = `CTS-DEMO-${String(item.attempt.attempt).padStart(4, "0")}`;
  }
  setCustomerPresentation(item);
  renderOperations(byId("ops-body"), byId("ops-replay-badge"), item?.operations || null);
  renderAuthoritativeTimeline(byId("demo-timeline"), demoController.history, {
    currentIndex: position,
  });
  byId("demo-timeline-position").textContent = total
    ? `${total} recorded attempt${total === 1 ? "" : "s"}`
    : "No attempts recorded";
  updateDemoButtons();
}

function updateDemoButtons() {
  const started = demoId !== null;
  const atRecordedEnd = demoController.atEnd;
  byId("start-demo").disabled = requestPending;
  byId("reset-demo").disabled = !started || requestPending;
  byId("play-demo").disabled = !started || demoComplete || requestPending;
  byId("previous-step").disabled = !started || demoController.atStart || requestPending;
  byId("next-step").disabled = !started || (demoComplete && atRecordedEnd) || requestPending;
  byId("customer-pay").disabled = !started || (demoComplete && atRecordedEnd) || requestPending;
  byId("attempt-counter").textContent = String(demoController.current()?.position ?? 0);
  byId("attempt-total").textContent = demoTotalAttempts ?? "—";
}

async function loadScenarios() {
  const payload = await api.demoScenarios();
  const select = byId("scenario-select");
  clear(select);
  payload.items.forEach((scenario) => {
    const option = element("option", null, `${scenario.label} · ${scenario.attempts} attempts`);
    option.value = scenario.id;
    select.append(option);
  });
}

async function startDemo() {
  setMessage("");
  demoController.reset();
  requestPending = true;
  updateDemoButtons();
  try {
    const payload = await api.demoStart(byId("scenario-select").value);
    demoId = payload.demo_id;
    demoComplete = false;
    demoTotalAttempts = payload.total_attempts;
    byId("customer-amount").textContent = "—";
    byId("customer-card").textContent = "Synthetic card alias";
    byId("customer-order").textContent = "CTS-DEMO-0000";
    setCustomerPresentation(null);
    renderOperations(byId("ops-body"), byId("ops-replay-badge"), null);
    renderAuthoritativeTimeline(byId("demo-timeline"), []);
    byId("demo-timeline-position").textContent = "No attempts recorded";
  } finally {
    requestPending = false;
    updateDemoButtons();
  }
}

async function fetchNextStep() {
  if (!demoId || demoComplete || requestPending) return false;
  requestPending = true;
  setCustomerPresentation(demoController.current(), { processing: true });
  updateDemoButtons();
  try {
    const payload = await api.demoStep(demoId);
    demoComplete = Boolean(payload.complete);
    demoTotalAttempts = payload.total_attempts ?? demoTotalAttempts;
    if (payload.operations) demoController.push(payload);
    return !demoComplete;
  } finally {
    requestPending = false;
    setCustomerPresentation(demoController.current());
    updateDemoButtons();
  }
}

async function stepForward() {
  if (demoController.nextRecorded()) return true;
  return fetchNextStep();
}

async function resetDemo() {
  demoController.pause();
  await api.demoReset();
  demoId = null;
  demoComplete = false;
  demoTotalAttempts = null;
  demoController.reset();
  byId("play-demo").textContent = "Play";
  byId("customer-amount").textContent = "—";
  byId("customer-card").textContent = "Synthetic card alias";
  byId("customer-order").textContent = "CTS-DEMO-0000";
  setCustomerPresentation(null);
  renderOperations(byId("ops-body"), byId("ops-replay-badge"), null);
  renderAuthoritativeTimeline(byId("demo-timeline"), []);
  byId("demo-timeline-position").textContent = "No attempts recorded";
  setMessage("");
  updateDemoButtons();
}

function bindDemo() {
  byId("start-demo").addEventListener("click", () => startDemo().catch(showError));
  byId("reset-demo").addEventListener("click", () => resetDemo().catch(showError));
  byId("next-step").addEventListener("click", () => stepForward().catch(showError));
  byId("previous-step").addEventListener("click", () => demoController.previous());
  byId("customer-pay").addEventListener("click", () => stepForward().catch(showError));

  const play = byId("play-demo");
  play.addEventListener("click", () => {
    if (demoController.playing) {
      demoController.pause();
      play.textContent = "Play";
      return;
    }
    play.textContent = "Pause";
    demoController.play(stepForward, (error) => {
      play.textContent = "Play";
      if (error) showError(error);
      updateDemoButtons();
    });
  });
  updateDemoButtons();
}

function renderVerifiedResults(metrics) {
  const container = byId("verified-results-grid");
  clear(container);
  const policy = metrics.operational_policy;
  const legitimate = metrics.denominators.legitimate_devices;
  const results = [
    [percent(policy.attacker_review_or_higher.rate, 2), "of attacker devices reached review or higher"],
    [percent(policy.attacker_block.rate, 2), "of attacker devices were blocked"],
    [`${policy.legitimate_review_or_higher} of ${legitimate.toLocaleString()}`, "legitimate devices were reviewed"],
    [`${policy.legitimate_blocks} of ${legitimate.toLocaleString()}`, "legitimate devices were blocked"],
  ];
  results.forEach(([value, label]) => {
    const item = element("div", "result-item");
    item.append(element("strong", null, value), element("span", null, label));
    container.append(item);
  });
}

async function initialize() {
  bindDemo();
  setMessage("Loading verified evidence and runtime state…", "loading");
  try {
    const readiness = await api.readiness();
    const status = byId("header-status");
    status.querySelector("[data-status-text]").textContent = readiness.ready ? "Protection ready" : "Not ready";
    status.classList.toggle("is-ready", Boolean(readiness.ready));
    status.classList.toggle("is-down", !readiness.ready);
    if (!readiness.ready) throw new Error(readiness.error || "The protection service is not ready.");
    const [metrics] = await Promise.all([api.blindMetrics(), loadScenarios()]);
    renderVerifiedResults(metrics);
    setMessage("");
  } catch (error) {
    byId("header-status").classList.add("is-down");
    showError(error);
  }
}

initialize();
