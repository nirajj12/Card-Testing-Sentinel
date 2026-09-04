import { ArrowRight, BadgeCheck, Check, CreditCard, History, LockKeyhole, RefreshCw, ShieldCheck, Webhook } from "lucide-react";

const available = [
  "Current amount and merchant",
  "Device and session references",
  "IP and customer references",
  "Timing and recent attempt velocity",
  "Previously verified successes or failures",
  "Historical protected-card patterns",
];
const unavailable = ["Current card number, CVV, or expiry", "Current payment result", "Current Razorpay outcome"];

export function CausalBoundary() {
  return <section className="hiw-causal" aria-labelledby="causal-title"><div className="page-width">
    <header className="hiw-section-heading aligned"><span>The decision-time boundary</span><h2 id="causal-title">Sentinel cannot use information from the future.</h2><p>The risk decision is made before the customer enters card details or Razorpay processes a payment.</p></header>
    <div className="hiw-boundary-grid">
      <article className="available"><div className="hiw-boundary-title"><span><ShieldCheck aria-hidden="true" /></span><div><small>Available at precheck</small><h3>What Sentinel can use</h3></div></div><ul>{available.map(item => <li key={item}><Check aria-hidden="true" />{item}</li>)}</ul></article>
      <div className="hiw-boundary-divider" aria-hidden="true"><i /><span>Decision happens here</span><ArrowRight /><i /></div>
      <article className="unavailable"><div className="hiw-boundary-title"><span><LockKeyhole aria-hidden="true" /></span><div><small>Not available yet</small><h3>What does not exist yet</h3></div></div><ul>{unavailable.map(item => <li key={item}><span />{item}</li>)}</ul></article>
    </div>
    <div className="hiw-causal-callout"><ShieldCheck aria-hidden="true" /><div><strong>The current payment result cannot influence its own risk decision.</strong><p>Only a later, verified result can help Sentinel understand a future checkout.</p></div></div>
  </div></section>;
}

const feedback = [
  [CreditCard, "Payment Result", "Razorpay completes the attempt"],
  [Webhook, "Signed Webhook", "Razorpay sends the outcome"],
  [BadgeCheck, "Verify + Deduplicate", "Sentinel checks the source"],
  [History, "Trusted Future History", "The verified result is stored"],
  [RefreshCw, "Next Precheck", "A future checkout can use it"],
] as const;

export function TrustedOutcomeLoop() {
  return <section className="hiw-feedback" aria-labelledby="feedback-title"><div className="page-width">
    <header className="hiw-section-heading aligned"><span>After an allowed payment</span><h2 id="feedback-title">A verified result helps the next decision—not this one.</h2><p>This smaller loop begins after the payment path shown in the architecture.</p></header>
    <div className="hiw-feedback-shell">
      <ol aria-label="Trusted payment outcome feedback loop">{feedback.map(([Icon, label, description], index) => <li className={label === "Verify + Deduplicate" ? "verified" : ""} key={label}><span><Icon aria-hidden="true" /></span><div><strong>{label}</strong><small>{description}</small></div>{index < feedback.length - 1 && <ArrowRight aria-hidden="true" />}</li>)}</ol>
      <p><ShieldCheck aria-hidden="true" /><span><strong>Browser callbacks are not trusted evidence.</strong> History changes only after Sentinel verifies the signed Razorpay webhook and rejects duplicates.</span></p>
    </div>
  </div></section>;
}
