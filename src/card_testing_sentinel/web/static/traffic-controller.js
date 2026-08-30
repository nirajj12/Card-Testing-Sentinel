import { api } from "./api-client.js";

/* Drives a mixed merchant-traffic run.

   The controller has no idea what any device "is". It starts a run, asks the
   server for the next payment, and paints whatever decision comes back. The
   scenario each device is running lives on the server and is only ever
   fetched through the separate `trafficTruth` call, which the operator has
   to ask for. That separation is the point: nothing on this side of the wire
   could leak an answer into a decision, because this side never has one
   until after every decision is made.

   Playback uses the same self-scheduling timeout pattern as ReplayController:
   each tick waits for its request to finish, so a slow response can never
   stack requests on top of each other or reorder the feed. */
export class TrafficController {
  constructor({ onPayment, onTotals, onLifecycle, onComplete, onError }) {
    this.onPayment = onPayment;
    this.onTotals = onTotals;
    this.onLifecycle = onLifecycle;
    this.onComplete = onComplete;
    this.onError = onError;
    this.runId = null;
    this.running = false;
    this.complete = false;
    this.timer = null;
    this.speed = 420;
    /* device_key -> payments, in the order the device made them. This is the
       only client-side aggregation, and it is a plain regrouping of rows the
       server already sent -- never a recomputation of anything. */
    this.byDevice = new Map();
    this.payments = [];
    this.totals = null;
  }

  get started() {
    return this.runId !== null;
  }

  async start() {
    this.stop();
    this.reset();
    const payload = await api.trafficStart();
    this.runId = payload.traffic_run_id;
    this.totalPayments = payload.total_payments;
    this.deviceCount = payload.device_count;
    this.totals = payload.run_totals;
    this.onTotals?.(this.totals, payload);
    return payload;
  }

  reset() {
    this.runId = null;
    this.complete = false;
    this.byDevice = new Map();
    this.payments = [];
    this.totals = null;
  }

  attemptsFor(deviceKey) {
    return this.byDevice.get(deviceKey) || [];
  }

  async step() {
    if (!this.runId || this.complete) return false;
    const payload = await api.trafficStep(this.runId);

    /* Outcomes and checkouts land later on the virtual clock than the
       decision they belong to. Patching the already-rendered row here is
       what makes the causal separation visible: the decision existed
       before its processor outcome did. */
    (payload.lifecycle_updates || []).forEach((update) => {
      const attempts = this.byDevice.get(update.device_key);
      const target = attempts?.find((row) => row.attempt === update.attempt);
      if (!target) return;
      const key = update.kind === "outcome" ? "outcome_status" : "checkout_status";
      target.operations[key] = update.status;
      this.onLifecycle?.(target, update);
    });

    if (payload.payment) {
      const payment = payload.payment;
      this.payments.push(payment);
      const bucket = this.byDevice.get(payment.device_key) || [];
      bucket.push(payment);
      this.byDevice.set(payment.device_key, bucket);
      this.onPayment?.(payment);
    }
    this.totals = payload.run_totals;
    this.onTotals?.(this.totals, payload);
    this.complete = Boolean(payload.complete);
    return !this.complete;
  }

  play() {
    if (this.running || this.complete) return;
    this.running = true;
    const tick = async () => {
      if (!this.running) return;
      let keepGoing = true;
      try {
        keepGoing = await this.step();
      } catch (error) {
        this.running = false;
        this.onError?.(error);
        return;
      }
      if (!this.running || !keepGoing) {
        this.running = false;
        this.onComplete?.();
        return;
      }
      this.timer = window.setTimeout(tick, this.speed);
    };
    tick();
  }

  stop() {
    this.running = false;
    if (this.timer) window.clearTimeout(this.timer);
    this.timer = null;
  }

  async truth() {
    if (!this.runId) return null;
    return api.trafficTruth(this.runId);
  }
}
