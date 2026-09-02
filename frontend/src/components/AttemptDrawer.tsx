import { X } from "lucide-react";
import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useRef } from "react";
import { decisionCopy, evidenceLabels, presentReason } from "../features/decision";
import { historyStatusLabel, paymentStatusLabel } from "../features/paymentLifecycle";
import type { ActivityAttempt } from "../types";

type AttemptDrawerProps = {
  attempt: ActivityAttempt | null;
  onClose: () => void;
};

export function AttemptDrawer({ attempt, onClose }: AttemptDrawerProps) {
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!attempt) return;

    previousFocusRef.current = document.activeElement as HTMLElement;
    const focusTimer = window.setTimeout(() => closeButtonRef.current?.focus(), 50);

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") closeDrawer();
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      window.clearTimeout(focusTimer);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [attempt]);

  function closeDrawer() {
    const returnTarget = previousFocusRef.current;
    onCloseRef.current();
    window.setTimeout(() => returnTarget?.focus(), 0);
  }

  if (!attempt) return null;

  const operation = attempt.operation;
  const score = operation.risk_score === null
    ? "Unavailable"
    : `${Math.round(operation.risk_score * 100)} / 100`;
  const evidence = Object.entries(operation.evidence || {})
    .filter(([key]) => key in evidenceLabels)
    .slice(0, 6);

  return (
    <AnimatePresence>
      <>
        <motion.button
          className="drawer-backdrop"
          aria-label="Close attempt details"
          onClick={closeDrawer}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
        />
        <motion.aside
          className="attempt-drawer"
          role="dialog"
          aria-modal="true"
          aria-labelledby="attempt-drawer-title"
          initial={{ x: "100%" }}
          animate={{ x: 0 }}
          exit={{ x: "100%" }}
        >
          <div className="drawer-head">
            <div>
              <span>Payment assessment</span>
              <h2 id="attempt-drawer-title">Attempt details</h2>
            </div>
            <button
              ref={closeButtonRef}
              type="button"
              onClick={closeDrawer}
              aria-label="Close attempt details"
            >
              <X />
            </button>
          </div>

          <div className="attempt-summary">
            <div>
              <span>Sentinel decision</span>
              <strong className={operation.decision}>{operation.decision.toUpperCase()}</strong>
            </div>
            <div>
              <span>Risk</span>
              <strong>{score}</strong>
            </div>
          </div>

          <section className="drawer-section">
            <span className="drawer-label">Signals at decision time</span>
            {evidence.length ? (
              <dl className="signal-list">
                {evidence.map(([key, value]) => (
                  <div key={key}>
                    <dt>{evidenceLabels[key]}</dt>
                    <dd>{value}</dd>
                  </div>
                ))}
              </dl>
            ) : (
              <p className="empty-evidence">
                No safe evidence snapshot is available for this attempt.
              </p>
            )}
          </section>

          {operation.reason_codes.length > 0 && (
            <section className="drawer-section">
              <span className="drawer-label">Why Sentinel chose this action</span>
              {operation.reason_codes.map((code) => {
                const reason = presentReason(code);
                return (
                  <div className="reason-detail" key={code}>
                    <strong>{reason.label}</strong>
                    <p>{reason.explanation}</p>
                    <code>{code}</code>
                  </div>
                );
              })}
            </section>
          )}

          <section className="drawer-section">
            <span className="drawer-label">Sentinel action</span>
            <p className="action-callout">{decisionCopy[operation.decision].copy}</p>
          </section>

          {attempt.source === "razorpay_test" && (
            <section className="drawer-section">
              <span className="drawer-label">Razorpay and payment lifecycle</span>
              <dl className="signal-list">
                <div>
                  <dt>Razorpay order created</dt>
                  <dd>{attempt.razorpay_order_created ? "YES" : "NO"}</dd>
                </div>
                <div>
                  <dt>Checkout opened</dt>
                  <dd>{attempt.checkout_opened ? "YES" : "NO"}</dd>
                </div>
                <div>
                  <dt>Checkout signature verified</dt>
                  <dd>{attempt.signature_verified ? "YES" : "NO"}</dd>
                </div>
                <div>
                  <dt>Signed webhook verified</dt>
                  <dd>{attempt.webhook_verified ? "YES" : "NO"}</dd>
                </div>
                <div>
                  <dt>Payment status</dt>
                  <dd>{paymentStatusLabel(attempt.razorpay_payment_status).toUpperCase()}</dd>
                </div>
                <div>
                  <dt>Behavioral history</dt>
                  <dd>{historyStatusLabel(attempt.history_status).toUpperCase()}</dd>
                </div>
              </dl>
            </section>
          )}

          <section className="drawer-section">
            <span className="drawer-label">Audit event</span>
            <code>{operation.protected_reference || "Protected reference unavailable"}</code>
            <small>
              {attempt.source === "replay"
                ? "Controlled synthetic replay"
                : "Razorpay Test Mode checkout"}
            </small>
          </section>
        </motion.aside>
      </>
    </AnimatePresence>
  );
}
