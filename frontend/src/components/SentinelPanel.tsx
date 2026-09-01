import { Check, CircleX, LoaderCircle } from "lucide-react";
import { AnimatePresence, motion } from "framer-motion";
import { decisionCopy, safeReason } from "../features/decision";
import { formatPrice } from "../data/products";
import type { Operation, VerifiedPayment } from "../types";

export type PaymentPhase = "idle" | "evaluating" | "decision" | "verifying" | "success" | "failure";

export function SentinelPanel({ phase, progress, operation, orderCreated, checkoutOpened, verified, paymentOutcome, historyStatus, amount, error }: { phase: PaymentPhase; progress: number; operation: Operation | null; orderCreated: boolean; checkoutOpened: boolean; verified: VerifiedPayment | null; paymentOutcome: string | null; historyStatus: string; amount: number; error: string }) {
  const view = operation ? decisionCopy[operation.decision] : null;
  const score = operation?.risk_score === null || operation?.risk_score === undefined ? null : Math.round(operation.risk_score * 100);
  return <article className={`sentinel-panel ${operation?.decision || "idle"}`}>
    <header className="sentinel-panel-head"><div><span>Live decision engine</span><h2>Sentinel Protection</h2></div><span className="monitoring"><i/>{phase === "evaluating" ? "Evaluating" : phase === "verifying" ? "Verifying" : "Monitoring"}</span></header>
    <div className="signal-ribbon"><span><i/>Velocity</span><span><i/>Decline history</span><span><i/>Session behavior</span></div>
    <AnimatePresence mode="wait">
      {phase === "idle" && <motion.div key="idle" className="sentinel-idle" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}><div className="sentinel-radar"><i/><i/><i/><b/></div><div><strong>Waiting for payment attempt</strong><p>Risk details appear here after the customer starts payment.</p></div></motion.div>}
      {phase === "evaluating" && <motion.div key="evaluating" className="evaluation-state" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}><div className="evaluation-visual"><LoaderCircle/><span/><span/></div><ol>{[["Request received","Payment intent protected"],["Behavioral history loaded","Verified outcomes reconstructed"],["Risk evaluated","Model and rules applied"],["Policy applied","Bounded action selected"]].map(([title, copy], index) => <li key={title} className={progress > index ? "done" : progress === index ? "active" : ""}><span>{progress > index ? <Check/> : index + 1}</span><div><strong>{title}</strong><small>{copy}</small></div><i/></li>)}</ol></motion.div>}
      {!['idle', 'evaluating'].includes(phase) && operation && view && <motion.div key="decision" className="decision-state" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
        <div className="decision-summary"><div className="risk-score"><span>Risk</span><strong>{score === null ? "—" : score}<small>/100</small></strong><i style={{ "--score-angle": `${(score || 0) * 2.3}deg` } as React.CSSProperties}/></div><div><span className={`decision-label ${operation.decision}`}>{view.label}</span><h3>{view.title}</h3><p>{view.copy}</p></div></div>
        <div className="decision-reasons">{operation.reason_codes.slice(0, 3).map((reason) => <span key={reason}><i/>{safeReason(reason)}</span>)}</div>
        <dl className="gateway-status"><div><dt>Razorpay order created</dt><dd className={orderCreated ? "yes" : "no"}>{orderCreated ? "YES" : "NO"}</dd></div><div><dt>Checkout opened</dt><dd className={checkoutOpened ? "yes" : "no"}>{checkoutOpened ? "YES" : "NO"}</dd></div></dl>
        {phase === "verifying" && <div className="verification-strip"><LoaderCircle/>Verifying the Razorpay signature on the backend…</div>}
        {paymentOutcome && <div className={`outcome-separation ${paymentOutcome === "failed" || paymentOutcome === "failed_unverified" ? "failed" : "verified"}`}>
          <div><span>Sentinel decision</span><strong>{operation.decision.toUpperCase()}</strong></div>
          <div><span>Razorpay outcome</span><strong>{paymentOutcome.replaceAll("_", " ").toUpperCase()}</strong></div>
          <div><span>Verified history</span><strong>{historyStatus.replaceAll("_", " ").toUpperCase()}</strong></div>
          {verified && <small><Check/>Checkout signature verified by the backend · {formatPrice(amount)}</small>}
          {error && <small className="outcome-error"><CircleX/>{error}</small>}
        </div>}
      </motion.div>}
      {phase === "failure" && !operation && <motion.div key="failure" className="payment-result failure" initial={{ opacity: 0, scale: .97 }} animate={{ opacity: 1, scale: 1 }}><div className="result-icon"><CircleX/></div><span>Payment not confirmed</span><h3>Payment flow stopped safely</h3><p>{error}</p></motion.div>}
    </AnimatePresence>
  </article>;
}
