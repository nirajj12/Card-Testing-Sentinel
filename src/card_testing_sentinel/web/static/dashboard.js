import { api } from "./api-client.js";
import { currency, customerState, integer, percent, scenarioDescription } from "./formatters.js";
import { ReplayController } from "./replay-controller.js";
import { TrafficController } from "./traffic-controller.js";
import {
  appendTrafficRow,
  clear,
  element,
  renderAuthoritativeTimeline,
  renderOperations,
  renderRiskDetail,
  renderRunTotals,
  renderTrajectory,
  renderTruth,
} from "./renderers.js";

const byId = (id) => document.getElementById(id);
const messageNode = byId("global-message");

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

/* ───────────────────────────── view shell ───────────────────────────── */

function showView(name) {
  /* Playback is bound to the view that owns it. Leaving Live Traffic while
     the loop is still stepping lets it race the next view's requests. */
  if (name !== "traffic" && traffic?.running) {
    traffic.stop();
    updateTrafficButtons();
  }
  document.querySelectorAll(".view").forEach((view) => {
    const active = view.id === `view-${name}`;
    view.hidden = !active;
    view.classList.toggle("is-active", active);
  });
  document.querySelectorAll(".view-tab").forEach((tab) => {
    const active = tab.dataset.view === name;
    tab.classList.toggle("is-active", active);
    tab.setAttribute("aria-selected", String(active));
  });
  window.scrollTo({ top: 0, behavior: "instant" });
}

function bindViews() {
  document.querySelectorAll(".view-tab").forEach((tab) => {
    tab.addEventListener("click", () => showView(tab.dataset.view));
  });
  /* Overview's job is to send a reader into the demo. Without these the best
     thing in the project is one unlabelled tab away. */
  document.querySelectorAll("[data-goto]").forEach((button) => {
    button.addEventListener("click", () => showView(button.dataset.goto));
  });
}

/* ───────────────────────────── Overview ───────────────────────────── */

/* Every figure here is read from the frozen blind-evaluation artifact via
   /api/metrics/blind. Nothing is computed in the browser and nothing is
   hardcoded except the latency benchmark, which is a local measurement the
   API does not serve (see scripts/benchmark.py) and is labelled as such. */
function renderOverview(metrics) {
  const policy = metrics.operational_policy;
  const impact = metrics.legitimate_impact;
  const failures = metrics.failure_modes || {};
  const devices = impact.devices;
  const rate = (count) => percent(devices ? count / devices : 0, 2);

  byId("m-recall").textContent = percent(policy.attacker_review_or_higher.rate, 1);
  byId("m-reviewed").textContent = `${impact.reviewed} / ${integer(devices)}`;
  byId("m-reviewed-sub").textContent = rate(impact.reviewed);
  byId("m-blocked").textContent = `${impact.blocked} / ${integer(devices)}`;
  byId("m-blocked-sub").textContent = rate(impact.blocked);

  renderCompare(metrics.baseline_comparison);

  if (failures.attacker_devices) {
    byId("limitation-detail").textContent =
      `${failures.never_detected} of ${failures.attacker_devices} attacker devices were not ` +
      `detected in the frozen held-out evaluation.`;
  }
}

/* A compact three-column answer to "why not just count attempts?". The two
   counter columns and the Sentinel column are read straight from the frozen
   baseline artifact. The trade-off row is only asserted while the artifact's
   own dominance check still says no simple threshold beats Sentinel on both
   axes -- if that ever changes it renders "—" instead of a stale claim. */
function renderCompare(comparison) {
  const host = byId("compare-table");
  clear(host);
  const rows = comparison?.baselines || [];
  const pick = (id) => rows.find((row) => row.id === id);
  const five = pick("count_ge_5");
  const sentinel = pick("sentinel_review_or_higher");
  const ten = pick("count_ge_10");
  if (!five || !sentinel || !ten) {
    host.append(element("p", "compare-empty", "Baseline comparison artifact is not loaded."));
    byId("compare-note").textContent = "";
    return;
  }

  const columns = [
    { title: "Count ≥ 5", data: five },
    { title: "Sentinel", data: sentinel, mark: true },
    { title: "Count ≥ 10", data: ten },
  ];
  const dominated = Boolean(comparison?.dominance?.dominated);

  const table = element("table", "cmp");
  const thead = element("thead");
  const headRow = element("tr");
  headRow.append(element("th", null, ""));
  columns.forEach((col) => headRow.append(element("th", col.mark ? "is-sentinel" : null, col.title)));
  thead.append(headRow);
  table.append(thead);

  const body = element("tbody");
  const addRow = (label, valueFor) => {
    const tr = element("tr");
    tr.append(element("th", null, label));
    columns.forEach((col) =>
      tr.append(element("td", col.mark ? "is-sentinel" : null, valueFor(col))),
    );
    body.append(tr);
  };
  addRow("Attacker detection", (col) => percent(col.data.attacker_recall, 1));
  addRow(
    "Legitimate devices flagged",
    (col) => `${col.data.legitimate_flagged} of ${integer(col.data.legitimate_devices)}`,
  );
  addRow("Useful trade-off", (col) => (dominated ? "—" : col.mark ? "✓" : "✕"));
  table.append(body);
  host.append(table);

  byId("compare-note").textContent = comparison?.dominance?.statement || "";
}

/* ───────────────────────────── Live Traffic ───────────────────────────── */

let selectedPayment = null;

function paintSelection(payment) {
  selectedPayment = payment;
  renderRiskDetail(byId("risk-detail"), payment);
  renderTrajectory(
    byId("risk-trajectory"),
    payment?.device_key,
    payment ? traffic.attemptsFor(payment.device_key) : [],
  );
  document.querySelectorAll(".feed-row").forEach((row) => {
    row.classList.toggle("is-selected", Number(row.dataset.sequence) === payment?.sequence);
  });
}

function updateTrafficButtons() {
  byId("traffic-start").textContent = traffic.started ? "Restart traffic" : "Start Synthetic Merchant Traffic";
  byId("traffic-pause").disabled = !traffic.started || traffic.complete;
  byId("traffic-pause").textContent = traffic.running ? "Pause" : "Resume";
  byId("traffic-stepone").disabled = !traffic.started || traffic.complete || traffic.running;
  byId("truth-reveal").disabled = !traffic.started || traffic.payments.length === 0;
}

function updateProgress() {
  const node = byId("feed-progress");
  if (!traffic.started) {
    node.textContent = "Not started";
    return;
  }
  const done = traffic.payments.length;
  node.textContent = traffic.complete
    ? `Run complete · ${done} payments across ${traffic.deviceCount} devices`
    : `${done} of ${traffic.totalPayments} payments · ${traffic.deviceCount} devices`;
}

const traffic = new TrafficController({
  onPayment: (payment) => {
    const feed = byId("traffic-feed");
    appendTrafficRow(feed, payment, paintSelection);
    applyFeedFilter();
    feed.scrollTop = 0;
    /* Auto-follow the first genuinely interesting decision so an operator
       watching the feed is not required to catch it by hand. */
    if (!selectedPayment || payment.operations.decision !== "allow") paintSelection(payment);
    updateProgress();
  },
  onTotals: (totals) => renderRunTotals(byId("run-totals"), totals),
  onLifecycle: (payment) => {
    if (selectedPayment && selectedPayment.sequence === payment.sequence) paintSelection(payment);
  },
  onComplete: () => {
    updateTrafficButtons();
    updateProgress();
    setMessage("Traffic run complete. Reveal ground truth to check the decisions against what was generated.", "success");
  },
  onError: (error) => {
    updateTrafficButtons();
    showError(error);
  },
});

let feedFilter = "all";

/* 58 payments, 10 of them acted on. Without this an operator scrolling the
   feed can miss every interesting decision in the run. */
function applyFeedFilter() {
  document.querySelectorAll("#traffic-feed .feed-row").forEach((row) => {
    const flagged = row.classList.contains("review") || row.classList.contains("block");
    row.classList.toggle("is-filtered", feedFilter === "flagged" && !flagged);
  });
}

function bindFeedFilter() {
  document.querySelectorAll("[data-feed-filter]").forEach((button) => {
    button.addEventListener("click", () => {
      feedFilter = button.dataset.feedFilter;
      document.querySelectorAll("[data-feed-filter]").forEach((other) => {
        const active = other.dataset.feedFilter === feedFilter;
        other.classList.toggle("is-active", active);
        other.setAttribute("aria-pressed", String(active));
      });
      applyFeedFilter();
    });
  });
}

function bindTraffic() {
  bindFeedFilter();
  byId("traffic-start").addEventListener("click", async () => {
    try {
      setMessage("");
      traffic.stop();
      clear(byId("traffic-feed"));
      byId("traffic-feed").append(element("p", "feed-empty", "Waiting for the first payment…"));
      clear(byId("truth-body"));
      selectedPayment = null;
      paintSelection(null);
      const started = await traffic.start();
      /* Every run draws a new device mix, so the feed differs each time. The
         seed is shown because a run nobody can reproduce cannot be inspected
         twice. */
      byId("traffic-seed-note").textContent =
        `Each run draws a different device mix · seed ${started.seed}`;
      updateProgress();
      updateTrafficButtons();
      traffic.play();
      updateTrafficButtons();
    } catch (error) {
      showError(error);
    }
  });

  byId("traffic-pause").addEventListener("click", () => {
    if (traffic.running) traffic.stop();
    else traffic.play();
    updateTrafficButtons();
  });

  byId("traffic-stepone").addEventListener("click", async () => {
    try {
      await traffic.step();
      updateProgress();
      updateTrafficButtons();
    } catch (error) {
      showError(error);
    }
  });

  byId("truth-reveal").addEventListener("click", async () => {
    try {
      const payload = await traffic.truth();
      renderTruth(byId("truth-body"), payload);
      byId("truth-reveal").disabled = true;
    } catch (error) {
      showError(error);
    }
  });

  renderRunTotals(byId("run-totals"), { payments: 0, allow: 0, review: 0, block: 0 });
  paintSelection(null);
  updateTrafficButtons();
}

/* ───────────────────────────── Replay Lab ───────────────────────────── */

let demoId = null;
let demoComplete = false;
let demoTotalAttempts = null;
let requestPending = false;
let selectedScenario = null;

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
  statusText.textContent = customerState(operations);
  payLabel.textContent = demoComplete ? "Replay complete" : "Pay next attempt";

  if (!operations) {
    statusText.textContent = demoId
      ? "Ready for the next synthetic payment."
      : "Choose a behaviour plan and start a replay.";
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
  renderAuthoritativeTimeline(byId("demo-timeline"), demoController.history, { currentIndex: position });
  if (total && demoComplete) {
    const steps = demoController.history;
    const firstFlag = steps.find((step) => step.operations.decision !== "allow");
    const firstBlock = steps.find((step) => step.operations.decision === "block");
    byId("demo-timeline-position").textContent =
      `${total} attempts · first intervention ${firstFlag ? `attempt ${firstFlag.attempt.attempt}` : "none"}` +
      ` · first block ${firstBlock ? `attempt ${firstBlock.attempt.attempt}` : "none"}`;
  } else {
    byId("demo-timeline-position").textContent = total
      ? `${total} recorded attempt${total === 1 ? "" : "s"}`
      : "No attempts recorded";
  }
  updateDemoButtons();
}

function updateDemoButtons() {
  const started = demoId !== null;
  const atRecordedEnd = demoController.atEnd;
  byId("start-demo").disabled = requestPending || !selectedScenario;
  byId("play-demo").disabled = !started || demoComplete || requestPending;
  byId("previous-step").disabled = !started || demoController.atStart || requestPending;
  byId("next-step").disabled = !started || (demoComplete && atRecordedEnd) || requestPending;
  byId("customer-pay").disabled = !started || (demoComplete && atRecordedEnd) || requestPending;
  byId("attempt-counter").textContent = String(demoController.current()?.position ?? 0);
  /* The plan length is deliberately withheld until the replay finishes.
     Telling an operator "Burst Card Testing — 8 attempts" before the
     detector runs frames the whole demonstration around an answer the
     detector was never given. */
  byId("attempt-total").textContent = demoComplete && demoTotalAttempts ? demoTotalAttempts : "—";
}

async function loadScenarios() {
  const payload = await api.demoScenarios();
  const container = byId("scenario-cards");
  clear(container);
  payload.items.forEach((scenario, index) => {
    const card = element("button", "scenario-card");
    card.type = "button";
    card.setAttribute("role", "radio");
    card.dataset.scenario = scenario.id;
    card.append(
      element("strong", null, scenario.label),
      element("span", null, scenarioDescription(scenario.id)),
    );
    card.addEventListener("click", () => selectScenario(scenario.id));
    container.append(card);
    if (index === 0) selectScenario(scenario.id);
  });
}

function selectScenario(id) {
  selectedScenario = id;
  document.querySelectorAll(".scenario-card").forEach((card) => {
    const active = card.dataset.scenario === id;
    card.classList.toggle("is-selected", active);
    card.setAttribute("aria-checked", String(active));
  });
  updateDemoButtons();
}

async function startDemo() {
  if (!selectedScenario) return;
  setMessage("");
  demoController.reset();
  requestPending = true;
  updateDemoButtons();
  try {
    const payload = await api.demoStart(selectedScenario);
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

function bindDemo() {
  byId("start-demo").addEventListener("click", () => startDemo().catch(showError));
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

/* ───────────────────────────── bootstrap ───────────────────────────── */

async function initialize() {
  bindViews();
  bindDemo();
  bindTraffic();
  setMessage("Loading runtime state and frozen evaluation evidence…", "loading");
  try {
    const readiness = await api.readiness();
    const status = byId("header-status");
    status.querySelector("[data-status-text]").textContent = readiness.ready ? "Protection ready" : "Not ready";
    status.classList.toggle("is-ready", Boolean(readiness.ready));
    status.classList.toggle("is-down", !readiness.ready);
    if (!readiness.ready) throw new Error(readiness.error || "The protection service is not ready.");
    const [metrics] = await Promise.all([api.blindMetrics(), loadScenarios()]);
    renderOverview(metrics);
    setMessage("");
  } catch (error) {
    byId("header-status").classList.add("is-down");
    showError(error);
  }
}

initialize();
