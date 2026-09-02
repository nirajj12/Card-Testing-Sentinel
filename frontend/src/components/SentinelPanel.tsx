import { AnimatePresence, motion } from "framer-motion";
import { Check, CircleX, LoaderCircle } from "lucide-react";
import { formatPrice } from "../data/products";
import { decisionCopy, presentReason } from "../features/decision";
import { historyStatusLabel, paymentStatusLabel } from "../features/paymentLifecycle";
import type {
  Operation,
  PaymentFailureContext,
  PaymentPhase,
  VerifiedPayment,
} from "../types";
import { LifecycleTracker } from "./LifecycleTracker";

type SentinelPanelProps = {
  phase: PaymentPhase;
  progress: number;
  operation: Operation | null;
  orderCreated: boolean;
  checkoutOpened: boolean;
  verified: VerifiedPayment | null;
  paymentOutcome: string | null;
  historyStatus: string;
  amount: number;
  error: string;
  failureContext?: PaymentFailureContext | null;
};

const EVALUATION_STEPS = [
  ["Request received", "Payment intent received before Razorpay order creation"],
  ["Behavioral history loaded", "Only prior verified outcomes are reconstructed"],
  ["Risk evaluated", "Model and deterministic rules assess observed behavior"],
  ["Policy applied", "Sentinel selects ALLOW, REVIEW, or BLOCK"],
] as const;

function monitoringLabel(phase: PaymentPhase) {
  if (phase === "sentinel_evaluating") return "Evaluating";
  if (phase === "signature_verifying") return "Verifying signature";
  if (phase === "awaiting_authoritative_status") return "Awaiting payment status";
  return "Monitoring";
}

function failureTitle(context: PaymentFailureContext | null | undefined) {
  if (context === "order") {
    return "Sentinel allowed this attempt, but the Razorpay order could not be created.";
  }
  if (context === "checkout") {
    return "Sentinel allowed this attempt, but Razorpay Checkout could not open.";
  }
  if (context === "verification") {
    return "The payment result could not be verified by the backend.";
  }
  return "The payment path stopped before a processor result was confirmed.";
}

export function SentinelPanel({
  phase,
  progress,
  operation,
  orderCreated,
  checkoutOpened,
  verified,
  paymentOutcome,
  historyStatus,
  amount,
  error,
  failureContext,
}: SentinelPanelProps) {
  const view = operation ? decisionCopy[operation.decision] : null;
  const score =
    operation?.risk_score === null || operation?.risk_score === undefined
      ? null
      : Math.round(operation.risk_score * 100);

  return (
    <article className={`sentinel-panel ${operation?.decision || "idle"}`}>
      <header className="sentinel-panel-head">
        <div>
          <span>Pre-payment risk decision</span>
          <h2>Sentinel Protection</h2>
        </div>
        <span className="monitoring">
          <i />
          {monitoringLabel(phase)}
        </span>
      </header>

      <LifecycleTracker
        phase={phase}
        operation={operation}
        orderCreated={orderCreated}
        checkoutOpened={checkoutOpened}
        verified={verified}
        paymentOutcome={paymentOutcome}
        historyStatus={historyStatus}
      />

      <div className="signal-ribbon">
        <span>
          <i />
          Velocity
        </span>
        <span>
          <i />
          Decline history
        </span>
        <span>
          <i />
          Session behavior
        </span>
      </div>

      <AnimatePresence mode="wait">
        {phase === "idle" && (
          <motion.div
            key="idle"
            className="sentinel-idle"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
          >
            <div className="sentinel-radar">
              <i />
              <i />
              <i />
              <b />
            </div>
            <div>
              <strong>Waiting for payment attempt</strong>
              <p>Risk details appear here after the customer starts payment.</p>
            </div>
          </motion.div>
        )}

        {phase === "sentinel_evaluating" && (
          <motion.div
            key="evaluating"
            className="evaluation-state"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
          >
            <div className="evaluation-visual">
              <LoaderCircle />
              <span />
              <span />
            </div>
            <ol>
              {EVALUATION_STEPS.map(([title, copy], index) => (
                <li
                  key={title}
                  className={progress > index ? "done" : progress === index ? "active" : ""}
                >
                  <span>{progress > index ? <Check /> : index + 1}</span>
                  <div>
                    <strong>{title}</strong>
                    <small>{copy}</small>
                  </div>
                  <i />
                </li>
              ))}
            </ol>
          </motion.div>
        )}

        {phase !== "idle" &&
          phase !== "sentinel_evaluating" &&
          operation &&
          view && (
            <motion.div
              key="decision"
              className="decision-state"
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
            >
              <div className="decision-summary">
                <div className="risk-score">
                  <span>Risk</span>
                  <strong>
                    {score === null ? "—" : score}
                    <small>/100</small>
                  </strong>
                  <i
                    style={
                      { "--score-angle": `${(score || 0) * 2.3}deg` } as React.CSSProperties
                    }
                  />
                </div>
                <div>
                  <span className={`decision-label ${operation.decision}`}>
                    {view.label}
                  </span>
                  <h3>{view.title}</h3>
                  <p>{view.copy}</p>
                </div>
              </div>

              <div className="decision-reasons">
                {operation.reason_codes.slice(0, 5).map((reason) => {
                  const presentation = presentReason(reason);
                  return (
                    <span key={reason}>
                      <i />
                      <span>
                        <strong>{presentation.label}</strong>
                        <small>{presentation.explanation}</small>
                      </span>
                    </span>
                  );
                })}
              </div>

              <dl className="gateway-status">
                <div>
                  <dt>Razorpay order created</dt>
                  <dd className={orderCreated ? "yes" : "no"}>
                    {orderCreated ? "YES" : "NO"}
                  </dd>
                </div>
                <div>
                  <dt>Checkout opened</dt>
                  <dd className={checkoutOpened ? "yes" : "no"}>
                    {checkoutOpened ? "YES" : "NO"}
                  </dd>
                </div>
              </dl>

              {phase === "signature_verifying" && (
                <div className="verification-strip">
                  <LoaderCircle />
                  The backend is verifying the Razorpay Checkout signature…
                </div>
              )}

              {phase === "awaiting_authoritative_status" && (
                <div className="verification-strip">
                  <Check />
                  <div>
                    <strong>Payment signature verified</strong>
                    <small>
                      The Checkout response passed backend verification. Waiting for a signed
                      Razorpay server event before showing payment success.
                    </small>
                  </div>
                </div>
              )}

              {phase === "payment_complete" && (
                <div className="verification-strip">
                  <Check />
                  <div>
                    <strong>Authoritative payment complete</strong>
                    <small>
                      The signed payment state is {paymentStatusLabel(paymentOutcome).toLowerCase()}
                      {" "}and the verified outcome is available to behavioral history.
                    </small>
                  </div>
                </div>
              )}

              {phase === "failure" && error && failureContext !== "processor" && (
                <div className="flow-error" role="alert">
                  <CircleX />
                  <div>
                    <strong>{failureTitle(failureContext)}</strong>
                    <p>{error}</p>
                  </div>
                </div>
              )}

              {paymentOutcome && (
                <div
                  className={`outcome-separation ${
                    paymentOutcome === "failed" || paymentOutcome === "failed_unverified"
                      ? "failed"
                      : "verified"
                  }`}
                >
                  <div>
                    <span>Sentinel decision</span>
                    <strong>{operation.decision.toUpperCase()}</strong>
                  </div>
                  <div>
                    <span>Payment lifecycle state</span>
                    <strong>{paymentStatusLabel(paymentOutcome).toUpperCase()}</strong>
                  </div>
                  <div>
                    <span>Behavioral history</span>
                    <strong>{historyStatusLabel(historyStatus).toUpperCase()}</strong>
                  </div>
                  {verified && (
                    <small>
                      <Check />
                      Checkout response signature verified by the backend · {formatPrice(amount)}
                    </small>
                  )}
                  {error && (
                    <small className="outcome-error">
                      <CircleX />
                      {error}
                    </small>
                  )}
                </div>
              )}
            </motion.div>
          )}

        {phase === "failure" && !operation && (
          <motion.div
            key="failure"
            className="payment-result failure"
            initial={{ opacity: 0, scale: 0.97 }}
            animate={{ opacity: 1, scale: 1 }}
          >
            <div className="result-icon">
              <CircleX />
            </div>
            <span>Payment not confirmed</span>
            <h3>Payment flow stopped safely</h3>
            <p>{error}</p>
          </motion.div>
        )}
      </AnimatePresence>
    </article>
  );
}
