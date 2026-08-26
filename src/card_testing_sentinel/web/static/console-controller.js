import { api, ApiError } from "./api-client.js";
import { currency, latency, timestamp } from "./formatters.js";
import {
  element,
  clear,
  renderDecision,
  renderDecisionsTable,
  renderDetails,
  renderJson,
  renderJsonPlaceholder,
  renderReasons,
} from "./renderers.js";

const byId = (id) => document.getElementById(id);

/* Drives the API console: builds a real raw lifecycle request, posts it to the
   production endpoints, and shows the exact JSON that went out and came back. */
export class ConsoleController {
  constructor(onMessage) {
    this.onMessage = onMessage;
    this.run = Date.now().toString(36);
    this.sequence = 0;
    this.attempt = 0;
    this.deviceIndex = 1;
    this.cardIndex = 1;
    this.lastBody = null;
    this.lastRequestId = null;
    this.lastDecision = null;
    this.approvedRequestId = null;
    this.nodes = {
      device: byId("in-device"),
      session: byId("in-session"),
      card: byId("in-card"),
      bin: byId("in-bin"),
      ip: byId("in-ip"),
      amount: byId("in-amount"),
      currency: byId("in-currency"),
      campaign: byId("in-campaign"),
      decision: byId("console-decision"),
      reasons: byId("console-reasons"),
      meta: byId("console-meta"),
      request: byId("io-request"),
      response: byId("io-response"),
      status: byId("io-status"),
      path: byId("io-path"),
      latency: byId("console-latency"),
      table: byId("decisions-body"),
      attempt: byId("attempt-counter-console"),
    };
    this.buttons = {
      precheck: byId("send-precheck"),
      decline: byId("send-decline"),
      approve: byId("send-approve"),
      checkout: byId("send-checkout"),
      replay: byId("test-replay"),
      conflict: byId("test-conflict"),
      newDevice: byId("new-device"),
      nextCard: byId("next-card"),
      refresh: byId("refresh-decisions"),
    };
  }

  bind() {
    this.buttons.precheck.addEventListener("click", () => this.sendPrecheck());
    this.buttons.decline.addEventListener("click", () => this.sendOutcome("declined"));
    this.buttons.approve.addEventListener("click", () => this.sendOutcome("approved"));
    this.buttons.checkout.addEventListener("click", () => this.sendCheckout());
    this.buttons.replay.addEventListener("click", () => this.sendIdempotentRetry());
    this.buttons.conflict.addEventListener("click", () => this.sendConflict());
    this.buttons.refresh.addEventListener("click", () => this.loadDecisions());
    this.buttons.newDevice.addEventListener("click", () => this.newDevice());
    this.buttons.nextCard.addEventListener("click", () => this.rotateCard());
    this.setFollowUpEnabled(false);
    renderJsonPlaceholder(this.nodes.request, "// The exact JSON body will appear here.");
    renderJsonPlaceholder(this.nodes.response, "// The exact JSON response will appear here.");
  }

  /* ── helpers ── */

  nextSequence() {
    this.sequence += 1;
    return this.sequence;
  }

  newDevice() {
    this.deviceIndex += 1;
    this.cardIndex = 1;
    this.attempt = 0;
    this.approvedRequestId = null;
    this.nodes.device.value = `device-${String(this.deviceIndex).padStart(3, "0")}`;
    this.nodes.session.value = `session-${String(this.deviceIndex).padStart(3, "0")}-1`;
    this.nodes.card.value = "tok-card-001";
    this.setFollowUpEnabled(false);
    this.nodes.attempt.textContent = "0";
    this.onMessage("Fresh device. Its causal state starts empty.", "success");
  }

  rotateCard() {
    this.cardIndex += 1;
    this.nodes.card.value = `tok-card-${String(this.cardIndex).padStart(3, "0")}`;
    this.onMessage("Card rotated. Card diversity is a strong card-testing signal.", "success");
  }

  buildBody() {
    const attempt = this.attempt + 1;
    const sequence = this.nextSequence();
    return {
      request_id: `req-${this.run}-${sequence}`,
      event_id: `evt-${this.run}-${sequence}`,
      device_id: this.nodes.device.value.trim(),
      session_id: this.nodes.session.value.trim(),
      card_reference: this.nodes.card.value.trim(),
      card_bin: this.nodes.bin.value.trim(),
      ip_reference: this.nodes.ip.value.trim(),
      amount: Number(this.nodes.amount.value),
      currency: this.nodes.currency.value,
      timestamp: new Date().toISOString(),
      event_sequence: sequence,
      campaign_active: this.nodes.campaign.checked,
      __attempt: attempt,
    };
  }

  async withBusy(button, task) {
    const previous = button.disabled;
    button.disabled = true;
    button.classList.add("busy");
    try {
      return await task();
    } finally {
      button.classList.remove("busy");
      button.disabled = previous;
    }
  }

  showRequest(method, path, body) {
    this.nodes.path.textContent = path;
    document.querySelector(".io-method").textContent = method;
    renderJson(this.nodes.request, body);
  }

  showResponse(status, payload, ok) {
    this.nodes.status.textContent = `${status || "—"}`;
    this.nodes.status.className = `io-status ${ok ? "ok" : "err"}`;
    renderJson(this.nodes.response, payload);
  }

  setFollowUpEnabled(enabled, { blocked = false } = {}) {
    this.buttons.decline.disabled = !enabled || blocked;
    this.buttons.approve.disabled = !enabled || blocked;
    this.buttons.replay.disabled = !enabled;
    this.buttons.conflict.disabled = !enabled;
    this.buttons.checkout.disabled = true;
  }

  /* ── actions ── */

  async sendPrecheck() {
    const body = this.buildBody();
    const attempt = body.__attempt;
    delete body.__attempt;
    this.showRequest("POST", "/api/precheck", body);
    await this.withBusy(this.buttons.precheck, async () => {
      try {
        const { data, status } = await api.precheck(body);
        this.attempt = attempt;
        this.lastBody = body;
        this.lastRequestId = body.request_id;
        this.lastDecision = data;
        this.nodes.attempt.textContent = String(attempt);
        this.showResponse(status, data, true);
        this.paint(data);
        this.setFollowUpEnabled(true, { blocked: data.decision === "block" });
        if (data.decision === "block") {
          this.onMessage(
            "Blocked. This request is suppressed, and its outcome and checkout are now refused — but later requests from the device are still scored.",
            "success",
          );
        } else {
          this.onMessage("", "clear");
        }
        await this.loadDecisions();
      } catch (error) {
        this.failure(error);
      }
    });
  }

  async sendIdempotentRetry() {
    if (!this.lastBody) return;
    this.showRequest("POST", "/api/precheck", this.lastBody);
    await this.withBusy(this.buttons.replay, async () => {
      try {
        const { data, status } = await api.precheck(this.lastBody);
        this.showResponse(status, data, true);
        this.paint(data);
        this.onMessage(
          data.idempotent_replay
            ? "Identical retry returned the stored result with idempotent_replay = true. No second decision was created."
            : "Retry was treated as a new request.",
          "success",
        );
        await this.loadDecisions();
      } catch (error) {
        this.failure(error);
      }
    });
  }

  async sendConflict() {
    if (!this.lastBody) return;
    const tampered = { ...this.lastBody, amount: Number((this.lastBody.amount + 7.77).toFixed(2)) };
    this.showRequest("POST", "/api/precheck", tampered);
    await this.withBusy(this.buttons.conflict, async () => {
      try {
        const { data, status } = await api.precheck(tampered);
        this.showResponse(status, data, true);
        this.onMessage("Expected a conflict here, but the service accepted the request.", "error");
      } catch (error) {
        if (error instanceof ApiError && error.status === 409) {
          this.showResponse(409, error.payload, false);
          this.onMessage(
            "HTTP 409 as expected. The same event ID with different content is rejected instead of silently overwriting the stored decision.",
            "success",
          );
        } else {
          this.failure(error);
        }
      }
    });
  }

  async sendOutcome(result) {
    if (!this.lastRequestId) return;
    const button = result === "approved" ? this.buttons.approve : this.buttons.decline;
    const sequence = this.nextSequence();
    const body = {
      event_id: `evt-${this.run}-${sequence}`,
      request_id: this.lastRequestId,
      device_id: this.nodes.device.value.trim(),
      session_id: this.nodes.session.value.trim(),
      timestamp: new Date().toISOString(),
      event_sequence: sequence,
      authorization_result: result,
      decline_reason: result === "declined" ? "generic_decline" : null,
    };
    if (result === "approved") delete body.decline_reason;
    this.showRequest("POST", "/api/outcomes", body);
    await this.withBusy(button, async () => {
      try {
        const { data, status } = await api.outcome(body);
        this.showResponse(status, data, true);
        this.buttons.decline.disabled = true;
        this.buttons.approve.disabled = true;
        if (result === "approved") {
          this.approvedRequestId = this.lastRequestId;
          this.buttons.checkout.disabled = false;
        }
        this.onMessage(
          result === "declined"
            ? "Decline recorded. It can only influence later requests, never the one already decided."
            : "Approval recorded. You can now complete the checkout to reduce accumulated risk.",
          "success",
        );
      } catch (error) {
        this.failure(error);
      }
    });
  }

  async sendCheckout() {
    if (!this.approvedRequestId) return;
    const sequence = this.nextSequence();
    const body = {
      event_id: `evt-${this.run}-${sequence}`,
      request_id: this.approvedRequestId,
      device_id: this.nodes.device.value.trim(),
      session_id: this.nodes.session.value.trim(),
      timestamp: new Date().toISOString(),
      event_sequence: sequence,
    };
    this.showRequest("POST", "/api/checkouts", body);
    await this.withBusy(this.buttons.checkout, async () => {
      try {
        const { data, status } = await api.checkout(body);
        this.showResponse(status, data, true);
        this.buttons.checkout.disabled = true;
        this.approvedRequestId = null;
        this.onMessage(
          "Checkout recorded. A genuine purchase reduces this device's accumulated risk on later requests.",
          "success",
        );
      } catch (error) {
        this.failure(error);
      }
    });
  }

  async loadDecisions() {
    try {
      const payload = await api.decisions(25);
      renderDecisionsTable(this.nodes.table, payload.items, null);
    } catch {
      /* the table is secondary; the message area already shows real failures */
    }
  }

  /* ── painting ── */

  paint(data) {
    renderDecision(this.nodes.decision, data);
    renderReasons(this.nodes.reasons, data.reason_codes);
    this.nodes.latency.textContent = `decided in ${latency(data.latency_ms)}`;
    renderDetails(this.nodes.meta, {
      "Request ID": { text: data.request_id, mono: true },
      "Device state": `v${data.device_state_version}`,
      "Model": { text: data.model_version, mono: true },
      "Policy": { text: data.policy_version, mono: true },
      "Idempotent replay": data.idempotent_replay ? "Yes" : "No",
      "Amount sent": currency(this.nodes.amount.value, this.nodes.currency.value),
      "Processed at": timestamp(data.processed_at),
    });
  }

  failure(error) {
    const status = error instanceof ApiError ? error.status : 0;
    const payload =
      error instanceof ApiError && error.payload
        ? error.payload
        : { error: "unavailable", message: error.message };
    this.showResponse(status || "—", payload, false);
    clear(this.nodes.decision);
    this.nodes.decision.append(element("p", "decision-empty", "The request was not accepted."));
    this.onMessage(error.message, "error");
  }
}
