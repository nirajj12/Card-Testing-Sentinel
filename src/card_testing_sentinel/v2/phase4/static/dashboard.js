import { api } from "./api-client.js";
import { currency } from "./formatters.js";
import { ReplayController } from "./replay-controller.js";
import {
  renderBars,
  renderDecision,
  renderDetails,
  renderDeviceList,
  renderMetrics,
  renderReasons,
  renderSystem,
  renderTimeline,
} from "./renderers.js?v=phase4-2";

const byId = (id) => document.getElementById(id);
const message = byId("global-message");
let demoId = null;
let demoComplete = false;

function showError(error) {
  message.classList.remove("is-loading");
  message.textContent = error?.message || "The dashboard could not complete this action.";
  message.classList.remove("is-hidden");
}

function showLoading() {
  message.textContent = "Loading verified evidence and runtime state…";
  message.classList.add("is-loading");
  message.classList.remove("is-hidden");
}

function clearError() {
  message.classList.add("is-hidden");
  message.classList.remove("is-loading");
  message.textContent = "";
}

function switchView(name) {
  document.querySelectorAll(".nav-tab").forEach((tab) => tab.classList.toggle("is-active", tab.dataset.view === name));
  document.querySelectorAll(".view").forEach((view) => {
    const active = view.id === `view-${name}`;
    view.hidden = !active;
    view.classList.toggle("is-active", active);
  });
}

const controller = new ReplayController((item, position, total) => {
  renderDecision(byId("live-decision"), item);
  renderDetails(byId("request-summary"), item?.request ? {
    "Request": item.request.request_id,
    "Attempt": item.request.attempt,
    "Amount": currency(item.request.amount, item.request.currency),
    "Card reference": `Card ${item.request.card_number}`,
    "Campaign": item.request.campaign_active ? "Active" : "Inactive",
  } : {});
  renderReasons(byId("reason-codes"), item?.decision?.reason_codes || []);
  renderTimeline(byId("live-timeline"), item?.timeline || [], { empty: "Start a scenario to create causal state." });
  byId("timeline-position").textContent = total ? `Recorded ${position + 1} of ${total}` : "No requests";
});

async function loadOverview() {
  const payload = await api.blindMetrics();
  const metrics = payload;
  renderMetrics(byId("overview-metrics"), metrics, payload.recorded_runtime);
  const actions = metrics.action_counts;
  renderBars(byId("action-chart"), [
    { label: "Allow", value: actions.allow, className: "allow", display: actions.allow.toLocaleString() },
    { label: "Review", value: actions.review, className: "review", display: actions.review.toLocaleString() },
    { label: "Block", value: actions.block, className: "block", display: actions.block.toLocaleString() },
  ]);
  const subtype = metrics.operational_policy.subtype;
  renderBars(byId("subtype-chart"), Object.entries(subtype).map(([name, row]) => ({
    label: name,
    value: row.review_or_higher.rate,
    display: `${(row.review_or_higher.rate * 100).toFixed(1)}% review`,
  })));
}

async function loadSystem() {
  renderSystem(byId("system-grid"), await api.system());
}

async function loadScenarios() {
  const payload = await api.demoScenarios();
  const select = byId("scenario-select");
  select.replaceChildren();
  payload.items.forEach((scenario) => {
    const option = document.createElement("option");
    option.value = scenario.id;
    option.textContent = `${scenario.label} · ${scenario.attempts} attempts`;
    select.append(option);
  });
}

async function startDemo() {
  clearError();
  controller.reset();
  const payload = await api.demoStart(byId("scenario-select").value);
  demoId = payload.demo_id;
  demoComplete = false;
  await nextDemoStep();
}

async function nextDemoStep() {
  if (!demoId || demoComplete) return;
  clearError();
  const payload = await api.demoStep(demoId);
  demoComplete = payload.complete;
  if (payload.decision) controller.push(payload);
  if (demoComplete) {
    controller.pause();
    byId("play-demo").textContent = "Play";
  }
}

async function resetDemo() {
  await api.demoReset();
  demoId = null;
  demoComplete = false;
  controller.reset();
}

async function loadReplayDevices() {
  const detectedValue = byId("filter-detected").value;
  const payload = await api.replayDevices({
    population: byId("filter-population").value,
    attack_subtype: byId("filter-subtype").value,
    decision: byId("filter-decision").value,
    detected: detectedValue === "" ? "" : detectedValue,
    limit: 80,
  });
  byId("replay-count").textContent = `${payload.count} shown`;
  renderDeviceList(byId("replay-devices"), payload.items, loadReplayTimeline);
}

async function loadReplayTimeline(deviceId) {
  const payload = await api.replayTimeline(deviceId);
  renderTimeline(byId("replay-timeline"), payload.items);
}

function bindEvents() {
  document.querySelectorAll(".nav-tab").forEach((tab) => tab.addEventListener("click", () => switchView(tab.dataset.view)));
  byId("start-demo").addEventListener("click", () => startDemo().catch(showError));
  byId("reset-demo").addEventListener("click", () => resetDemo().catch(showError));
  byId("next-step").addEventListener("click", () => nextDemoStep().catch(showError));
  byId("previous-step").addEventListener("click", () => controller.previous());
  byId("speed-control").addEventListener("input", (event) => controller.setSpeed(event.target.value));
  byId("play-demo").addEventListener("click", (event) => {
    if (controller.timer) {
      controller.pause();
      event.currentTarget.textContent = "Play";
    } else {
      controller.play(() => nextDemoStep().catch(showError));
      event.currentTarget.textContent = "Pause";
    }
  });
  byId("apply-filters").addEventListener("click", () => loadReplayDevices().catch(showError));
}

async function initialize() {
  bindEvents();
  showLoading();
  try {
    const ready = await api.readiness();
    const status = byId("header-status");
    status.querySelector("span:last-child").textContent = ready.ready ? "System ready" : "Not ready";
    status.classList.toggle("is-ready", ready.ready);
    if (!ready.ready) throw new Error(ready.error || "The application is not ready.");
    await Promise.all([loadOverview(), loadSystem(), loadScenarios(), loadReplayDevices()]);
    clearError();
  } catch (error) {
    showError(error);
  }
}

initialize();
