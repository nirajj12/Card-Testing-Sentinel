import { X } from "lucide-react";
import { AnimatePresence, motion } from "framer-motion";
import { evidenceLabels } from "../features/decision";
import type { ActivityAttempt } from "../types";

export function AttemptDrawer({ attempt, onClose }: { attempt: ActivityAttempt | null; onClose: () => void }) {
  if (!attempt) return null;
  const op = attempt.operation;
  const score = op.risk_score === null ? "Unavailable" : `${Math.round(op.risk_score * 100)} / 100`;
  const evidence = Object.entries(op.evidence || {}).filter(([key]) => key in evidenceLabels).slice(0, 6);
  return <AnimatePresence><><motion.button className="drawer-backdrop" aria-label="Close attempt details" onClick={onClose} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}/><motion.aside className="attempt-drawer" initial={{ x: "100%" }} animate={{ x: 0 }} exit={{ x: "100%" }}>
    <div className="drawer-head"><div><span>Payment assessment</span><h2>Attempt details</h2></div><button type="button" onClick={onClose}><X/></button></div>
    <div className="attempt-summary"><div><span>Decision</span><strong className={op.decision}>{op.decision === "block" ? "Temporary Block" : op.decision.toUpperCase()}</strong></div><div><span>Risk</span><strong>{score}</strong></div></div>
    <section className="drawer-section"><span className="drawer-label">Signals at decision time</span>{evidence.length ? <dl className="signal-list">{evidence.map(([key, value]) => <div key={key}><dt>{evidenceLabels[key]}</dt><dd>{value}</dd></div>)}</dl> : <p className="empty-evidence">No safe evidence snapshot is available for this attempt.</p>}</section>
    <section className="drawer-section"><span className="drawer-label">Action</span><p className="action-callout">{op.decision === "block" ? "Razorpay order suppressed" : op.decision === "review" ? "Merchant intervention recommended" : attempt.source === "replay" ? "Synthetic authorization path" : "Eligible for Razorpay order creation"}</p></section>
    {attempt.source === "razorpay_test" && <section className="drawer-section"><span className="drawer-label">Razorpay outcome</span><p className="action-callout">{attempt.razorpay_payment_status?.replaceAll("_", " ").toUpperCase() || "NO PAYMENT OUTCOME"}</p><small>Webhook verified: {attempt.webhook_verified ? "YES" : "NO"} · History: {attempt.history_status?.replaceAll("_", " ").toUpperCase() || "NOT RECORDED"}</small></section>}
    <section className="drawer-section"><span className="drawer-label">Audit event</span><code>{op.protected_reference || "Protected reference unavailable"}</code><small>{attempt.source === "replay" ? "Controlled synthetic replay" : "Razorpay Test Mode checkout"}</small></section>
  </motion.aside></></AnimatePresence>;
}
