import { ArrowLeft, FlaskConical, Mail, Minus, Phone, Plus, ShieldCheck } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ActivityFeed } from "../components/ActivityFeed";
import { AttemptDrawer } from "../components/AttemptDrawer";
import { ReplayDrawer } from "../components/ReplayDrawer";
import { SentinelPanel } from "../components/SentinelPanel";
import { formatPrice } from "../data/products";
import { normalizePrecheck } from "../features/decision";
import { phaseForPaymentStatus } from "../features/paymentLifecycle";
import { api, friendlyError } from "../lib/api";
import { randomHex } from "../lib/browserId";
import { useCart } from "../state/CartContext";
import type {
  ActivityAttempt,
  DurableActivity,
  Operation,
  PaymentFailureContext,
  PaymentPhase,
  PrecheckResponse,
  RazorpayOptions,
  RazorpayOrder,
  SystemStatus,
  VerifiedPayment,
} from "../types";

type ShopperIdentity = {
  device: string;
  session: string;
  sequence: number;
};

type CheckoutResponse = Parameters<RazorpayOptions["handler"]>[0];
type RequestFailureStage = Extract<PaymentFailureContext, "precheck" | "order" | "checkout">;

const BUSY_PHASES = new Set<PaymentPhase>([
  "sentinel_evaluating",
  "order_creating",
  "signature_verifying",
]);

function nextShopperIdentity(): ShopperIdentity {
  let device = sessionStorage.getItem("sentinel_store_device");
  let session = sessionStorage.getItem("sentinel_store_session");

  if (!device || !session) {
    const suffix = randomHex(14);
    device = `store-device-${suffix}`;
    session = `store-session-${suffix}`;
    sessionStorage.setItem("sentinel_store_device", device);
    sessionStorage.setItem("sentinel_store_session", session);
  }

  const sequence = Number(sessionStorage.getItem("sentinel_store_sequence") || "0") + 1;
  sessionStorage.setItem("sentinel_store_sequence", String(sequence));
  return { device, session, sequence };
}

function clearShopperIdentity() {
  sessionStorage.removeItem("sentinel_store_device");
  sessionStorage.removeItem("sentinel_store_session");
  sessionStorage.removeItem("sentinel_store_sequence");
}

async function loadRazorpayCheckout() {
  if (window.Razorpay) return;

  await new Promise<void>((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>(
      "script[data-razorpay-checkout]",
    );
    if (existing) {
      existing.addEventListener("load", () => resolve(), { once: true });
      existing.addEventListener(
        "error",
        () => reject(new Error("Checkout failed to load")),
        { once: true },
      );
      return;
    }

    const script = document.createElement("script");
    script.src = "https://checkout.razorpay.com/v1/checkout.js";
    script.dataset.razorpayCheckout = "true";
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("Checkout failed to load"));
    document.head.append(script);
  });

  if (!window.Razorpay) throw new Error("Razorpay Checkout is unavailable.");
}

function toActivityAttempt(
  item: DurableActivity,
  index: number,
  total: number,
): ActivityAttempt {
  return {
    id: item.id,
    attempt: total - index,
    amount: item.amount,
    currency: item.currency,
    timestamp: item.timestamp,
    source: item.source,
    operation: {
      decision: item.sentinel_decision,
      risk_score: item.risk_score,
      reason_codes: item.reason_codes,
      evidence: item.evidence,
      protected_reference: item.protected_reference,
    },
    razorpay_order_created: item.razorpay_order_created,
    checkout_opened: item.checkout_opened,
    razorpay_payment_status: item.razorpay_payment_status,
    signature_verified: item.signature_verified,
    webhook_verified: item.webhook_verified,
    history_status: item.history_status,
    payment_attempt_count: item.payment_attempt_count,
  };
}

function checkoutButtonLabel(phase: PaymentPhase) {
  if (phase === "sentinel_evaluating") return "Sentinel is checking…";
  if (phase === "order_creating") return "Creating Razorpay order…";
  if (phase === "signature_verifying") return "Verifying Checkout response…";
  return "Pay securely with Razorpay";
}

export function CheckoutPage() {
  const [searchParams] = useSearchParams();
  const cart = useCart();
  const ProductIcon = cart.product.icon;
  const amount = cart.product.price * cart.quantity;

  const [email, setEmail] = useState("builder@example.com");
  const [contact, setContact] = useState("+919876543210");
  const [phase, setPhase] = useState<PaymentPhase>("idle");
  const [progress, setProgress] = useState(0);
  const [operation, setOperation] = useState<Operation | null>(null);
  const [orderCreated, setOrderCreated] = useState(false);
  const [checkoutOpened, setCheckoutOpened] = useState(false);
  const [verified, setVerified] = useState<VerifiedPayment | null>(null);
  const [paymentOutcome, setPaymentOutcome] = useState<string | null>(null);
  const [historyStatus, setHistoryStatus] = useState("not_recorded");
  const [currentActivityId, setCurrentActivityId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [failureContext, setFailureContext] = useState<PaymentFailureContext | null>(null);
  const [activities, setActivities] = useState<ActivityAttempt[]>([]);
  const [selectedAttempt, setSelectedAttempt] = useState<ActivityAttempt | null>(null);
  const [replayOpen, setReplayOpen] = useState(Boolean(searchParams.get("demo")));
  const [system, setSystem] = useState<SystemStatus | null>(null);

  const refreshActivities = useCallback(async () => {
    const result = await api.recentActivity<{ items: DurableActivity[] }>();
    const next = result.items.map((item, index) =>
      toActivityAttempt(item, index, result.items.length),
    );
    setActivities(next);

    const current = currentActivityId
      ? next.find((item) => item.id === currentActivityId)
      : null;
    if (!current) return;

    setPaymentOutcome(current.razorpay_payment_status || null);
    setHistoryStatus(current.history_status || "not_recorded");
    const nextPhase = phaseForPaymentStatus(
      current.razorpay_payment_status,
      current.history_status,
    );
    if (nextPhase) setPhase(nextPhase);
  }, [currentActivityId]);

  useEffect(() => {
    api.system<SystemStatus>().then(setSystem).catch(() => setSystem(null));
  }, []);

  useEffect(() => {
    refreshActivities().catch(() => undefined);
    const timer = window.setInterval(
      () => refreshActivities().catch(() => undefined),
      2500,
    );
    return () => window.clearInterval(timer);
  }, [refreshActivities]);

  function addActivity(item: ActivityAttempt) {
    setActivities((current) => [item, ...current.filter((row) => row.id !== item.id)]);
  }

  function resetAttemptView() {
    setPhase("idle");
    setProgress(0);
    setOperation(null);
    setOrderCreated(false);
    setCheckoutOpened(false);
    setVerified(null);
    setPaymentOutcome(null);
    setHistoryStatus("not_recorded");
    setCurrentActivityId(null);
    setError("");
    setFailureContext(null);
  }

  function beginAttempt() {
    resetAttemptView();
    setPhase("sentinel_evaluating");
  }

  function startFreshTestShopper() {
    clearShopperIdentity();
    setEmail(`builder+${randomHex(10)}@example.com`);
    resetAttemptView();
  }

  async function verifyCheckoutResponse(
    payment: CheckoutResponse,
    requestId: string,
    shopper: ShopperIdentity,
  ) {
    setPhase("signature_verifying");
    setPaymentOutcome(null);
    setHistoryStatus("not_recorded");
    setError("");
    setFailureContext(null);

    try {
      const verification = await api.verifyPayment<VerifiedPayment>({
        sentinel_request_id: requestId,
        device_id: shopper.device,
        session_id: shopper.session,
        razorpay_order_id: payment.razorpay_order_id,
        razorpay_payment_id: payment.razorpay_payment_id,
        razorpay_signature: payment.razorpay_signature,
      });
      const nextHistoryStatus = verification.outcome_recorded
        ? "recorded_approved"
        : "awaiting_signed_webhook";

      setVerified(verification);
      setPaymentOutcome(verification.payment_status);
      setHistoryStatus(nextHistoryStatus);
      setPhase(
        phaseForPaymentStatus(verification.payment_status, nextHistoryStatus) ||
          "awaiting_authoritative_status",
      );
      refreshActivities().catch(() => undefined);
    } catch (verificationError) {
      setPaymentOutcome(null);
      setVerified(null);
      setHistoryStatus("not_recorded");
      setFailureContext("verification");
      setError(friendlyError(verificationError));
      setPhase("failure");
    }
  }

  function handleBrowserPaymentFailure() {
    setFailureContext("processor");
    setPaymentOutcome("failed_unverified");
    setHistoryStatus("awaiting_signed_webhook");
    setError(
      "Razorpay Checkout reported a payment failure. This browser event is not yet trusted history; Sentinel is waiting for the signed server event.",
    );
    setPhase("failure");
    window.setTimeout(() => refreshActivities().catch(() => undefined), 800);
  }

  function handleCheckoutDismissed() {
    setFailureContext("checkout");
    setError("Checkout was closed before a verified payment completed.");
    setPhase("failure");
  }

  async function openRazorpay(
    order: RazorpayOrder,
    requestId: string,
    shopper: ShopperIdentity,
  ) {
    await loadRazorpayCheckout();
    const checkout = new window.Razorpay!({
      key: order.key_id,
      amount: order.amount,
      currency: order.currency,
      name: "Northstar Store",
      description: `${cart.product.name} · Test purchase`,
      order_id: order.razorpay_order_id,
      prefill: { email, contact },
      theme: { color: "#2864f0" },
      handler: (payment) => verifyCheckoutResponse(payment, requestId, shopper),
      modal: { ondismiss: handleCheckoutDismissed },
    });

    checkout.on("payment.failed", handleBrowserPaymentFailure);
    checkout.open();
    setCheckoutOpened(true);
    setPhase("checkout_open");
    api.checkoutOpened({
      sentinel_request_id: requestId,
      device_id: shopper.device,
      session_id: shopper.session,
    }).then(() => refreshActivities()).catch(() => undefined);
  }

  async function pay() {
    if (!email || !contact || !email.includes("@")) {
      setError("Enter a valid email and mobile number.");
      setPhase("failure");
      return;
    }

    beginAttempt();
    let failureStage: RequestFailureStage = "precheck";
    const progressTimers = [150, 360, 580].map((delay, index) =>
      window.setTimeout(() => setProgress(index + 1), delay),
    );

    try {
      const shopper = nextShopperIdentity();
      const token = randomHex(18);
      const requestId = `store-request-${token}`;
      const timestamp = new Date().toISOString();
      const result = await api.precheck<PrecheckResponse>({
        request_id: requestId,
        event_id: `store-precheck-${token}`,
        merchant_id: "northstar-test-merchant",
        customer_id: email,
        device_id: shopper.device,
        session_id: shopper.session,
        ip_reference: "browser-test-reference",
        amount,
        currency: "INR",
        campaign_active: false,
        timestamp,
        event_sequence: shopper.sequence,
      });

      progressTimers.forEach(window.clearTimeout);
      setProgress(4);
      const nextOperation = normalizePrecheck(result);
      setOperation(nextOperation);
      setPhase("sentinel_decision");
      addActivity({
        id: requestId,
        attempt: activities.length + 1,
        amount,
        currency: "INR",
        timestamp,
        requestId,
        source: "razorpay_test",
        operation: nextOperation,
      });

      if (result.decision !== "allow") {
        refreshActivities().catch(() => undefined);
        return;
      }

      failureStage = "order";
      setPhase("order_creating");
      const order = await api.razorpayOrder<RazorpayOrder>({
        sentinel_request_id: requestId,
        device_id: shopper.device,
        session_id: shopper.session,
      });
      setOrderCreated(true);
      setCurrentActivityId(order.activity_id);
      setPhase("razorpay_order_created");

      failureStage = "checkout";
      await openRazorpay(order, requestId, shopper);
    } catch (requestError) {
      progressTimers.forEach(window.clearTimeout);
      setFailureContext(failureStage);
      setError(friendlyError(requestError));
      setPhase("failure");
    }
  }

  return (
    <main className="checkout-route page-width">
      <div className="checkout-route-head">
        <Link to="/">
          <ArrowLeft />
          Back home
        </Link>
        <div>
          <span>Try the Demo</span>
          <h1>Protected test checkout.</h1>
          <p>Watch every step from payment intent to verified outcome.</p>
        </div>
        <button type="button" onClick={() => setReplayOpen(true)}>
          <FlaskConical />
          Run attack replay
        </button>
      </div>

      <section className="checkout-grid">
        <article className="checkout-form-card">
          <div className="checkout-merchant">
            <span>N</span>
            <div>
              <strong>Northstar Store</strong>
              <small>Test Mode merchant checkout</small>
            </div>
            <i>
              <ShieldCheck />
              Secure
            </i>
          </div>

          <div className="checkout-product">
            <div
              style={{
                background: `linear-gradient(145deg,${cart.product.colors[0]},${cart.product.colors[1]})`,
              }}
            >
              <ProductIcon />
            </div>
            <div>
              <span>{cart.product.eyebrow}</span>
              <h2>{cart.product.name}</h2>
              <p>{cart.product.description}</p>
            </div>
            <strong>{formatPrice(amount)}</strong>
          </div>

          <div className="quantity-row checkout-quantity">
            <span>Quantity</span>
            <div>
              <button type="button" onClick={() => cart.setQuantity(cart.quantity - 1)}>
                <Minus />
              </button>
              <strong>{cart.quantity}</strong>
              <button type="button" onClick={() => cart.setQuantity(cart.quantity + 1)}>
                <Plus />
              </button>
            </div>
          </div>

          <div className="customer-fields">
            <label>
              <span>
                <Mail />
                Email address
              </span>
              <input
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
              />
            </label>
            <label>
              <span>
                <Phone />
                Mobile number
              </span>
              <input
                type="tel"
                value={contact}
                onChange={(event) => setContact(event.target.value)}
              />
            </label>
          </div>

          <dl className="order-summary">
            <div>
              <dt>Subtotal</dt>
              <dd>{formatPrice(amount)}</dd>
            </div>
            <div>
              <dt>Shipping</dt>
              <dd>Free</dd>
            </div>
            <div>
              <dt>Total</dt>
              <dd>{formatPrice(amount)}</dd>
            </div>
          </dl>

          <button
            className="razorpay-cta"
            type="button"
            onClick={pay}
            disabled={BUSY_PHASES.has(phase)}
          >
            <span>{checkoutButtonLabel(phase)}</span>
            <strong>{formatPrice(amount)}</strong>
          </button>

          {operation && operation.decision !== "allow" && (
            <div className="fresh-test-shopper">
              <div>
                <strong>This Test Mode shopper has remembered risk.</strong>
                <p>
                  Refreshing keeps the same identity and trusted history. Start fresh to test a
                  new shopper without deleting this evidence.
                </p>
              </div>
              <button type="button" onClick={startFreshTestShopper}>
                Start fresh Test Mode shopper
              </button>
            </div>
          )}

          <div className="checkout-footer">
            <span>
              <ShieldCheck />
              Protected by Sentinel
            </span>
            <span>Razorpay · Test Mode</span>
          </div>
        </article>

        <SentinelPanel
          phase={phase}
          progress={progress}
          operation={operation}
          orderCreated={orderCreated}
          checkoutOpened={checkoutOpened}
          verified={verified}
          paymentOutcome={paymentOutcome}
          historyStatus={historyStatus}
          amount={amount}
          error={error}
          failureContext={failureContext}
        />
      </section>

      <ActivityFeed attempts={activities} onSelect={setSelectedAttempt} />
      <AttemptDrawer attempt={selectedAttempt} onClose={() => setSelectedAttempt(null)} />
      <ReplayDrawer
        open={replayOpen}
        onClose={() => setReplayOpen(false)}
        onAttempt={addActivity}
        system={system}
        initialScenario={searchParams.get("demo") || undefined}
      />
    </main>
  );
}
