import { ArrowRight, CheckCircle2, CreditCard, Eye, Fingerprint, Gauge, History, RefreshCcw, ShieldCheck, Shuffle, XCircle } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { SignalCard } from "../components/SignalCard";

type HeroMode = "normal" | "burst";
const signalCards = [
  [Gauge, "Attempt velocity", "One attempt may look normal. Several attempts within a short period provide stronger evidence.", "1 attempt → 4 attempts → 8 attempts"],
  [RefreshCcw, "Retry behaviour", "A normal retry differs from repeated declines followed by rapid card-reference changes.", "One careful retry vs. a repeated automated sequence"],
  [Shuffle, "Card-reference diversity", "Protected card references reveal switching patterns without exposing raw card credentials.", "One protected reference → several changing references"],
  [Fingerprint, "Device and session consistency", "Attempts can remain connected through protected device and session context.", "Stable context vs. rapid session changes"],
  [History, "Verified decline history", "Only trusted prior outcomes help interpret what the next attempt means.", "Verified decline → retry → changing behaviour"],
  [Eye, "Merchant-side history", "Recent behaviour available to the merchant is evaluated before order creation.", "Past verified events inform the next precheck"],
] as const;

export function LandingPage() {
  const [mode, setMode] = useState<HeroMode>("normal");
  const suspicious = mode === "burst";
  return <main>
    <section className="home-hero page-width refined-hero">
      <div className="hero-copy"><span className="eyebrow-pill"><i/>Behavioural protection before authorization</span><h1>Stop card testing <em>before payment begins.</em></h1><p>Sentinel evaluates merchant-visible behaviour before a Razorpay order is created. It separates ordinary payment intent from repeated patterns that need intervention.</p><div className="hero-actions"><Link className="primary-cta" to="/checkout">Try protected checkout <ArrowRight/></Link><Link className="secondary-cta" to="/checkout?demo=burst_attacker">Run attack simulation</Link></div><p className="hero-disclaimer">Razorpay Test Mode · Synthetic scenarios · Sentinel never accepts or stores raw card credentials.</p></div>
      <div className={`hero-decision-stage ${mode}`} aria-label={`${suspicious ? "Suspicious burst" : "Normal purchase"} example decision flow`}>
        <div className="hero-mode-tabs" role="group" aria-label="Example flow"><button type="button" className={!suspicious ? "active" : ""} onClick={() => setMode("normal")}>Normal purchase</button><button type="button" className={suspicious ? "active" : ""} onClick={() => setMode("burst")}>Suspicious burst</button></div>
        <div className="intent-mini"><CreditCard/><span>Payment intent</span><strong>{suspicious ? "₹2 · ₹5 · ₹2" : "₹2,499"}</strong><small>{suspicious ? "Several protected references" : "One usual device"}</small></div>
        <div className="decision-boundary"><span className="boundary-ring"/><ShieldCheck/><span>Protected decision layer</span><strong>Sentinel</strong><div className="active-signals"><i/><i/><i/><i/></div><small>{suspicious ? "Velocity and diversity rising" : "No suspicious sequence accumulated"}</small></div>
        <div className="hero-paths"><div className={`allow ${!suspicious ? "selected" : ""}`}><CheckCircle2/><span>ALLOW</span><strong>Order creation permitted</strong></div><div className={`review ${suspicious ? "selected" : ""}`}><Eye/><span>REVIEW</span><strong>Order creation stopped</strong></div><div className={`block ${suspicious ? "selected" : ""}`}><XCircle/><span>TEMPORARY BLOCK</span><strong>Checkout does not open</strong></div></div>
        <div className={`razorpay-gate ${suspicious ? "closed" : "open"}`}><span>Razorpay order path</span><strong>{suspicious ? "Unavailable after intervention" : "Available after ALLOW"}</strong></div>
      </div>
    </section>

    <section className="section-block page-width"><header className="section-heading compact"><div><span>Behavioural evidence</span><h2>The current model combines 39 behavioural signals.</h2></div><p>Six plain-language groups explain what those signals observe. Open a card to see a realistic example; essential meaning never depends on hover.</p></header><div className="signal-story-grid">{signalCards.map(([icon,title,copy,example]) => <SignalCard key={title} icon={icon} title={title} copy={copy} example={example}/>)}</div></section>

    <section className="section-block process-section"><div className="page-width"><header className="section-heading"><div><span>The boundary</span><h2>One decision before order creation.</h2></div><Link className="text-arrow" to="/how-it-works">Follow three realistic stories <ArrowRight/></Link></header><div className="outcome-grid"><article className="allow"><CheckCircle2/><span>ALLOW</span><h3>Order creation permitted</h3><p>The backend may create a Razorpay Test order. Payment authorization still happens later through Razorpay.</p></article><article className="review"><Eye/><span>REVIEW</span><h3>Merchant intervention recommended</h3><p>No order is created. Sentinel does not claim an OTP, CAPTCHA, 3DS or manual-review workflow.</p></article><article className="block"><XCircle/><span>TEMPORARY BLOCK</span><h3>Attempt stopped for now</h3><p>No order is created and Checkout stays closed. The customer is not permanently banned.</p></article></div></div></section>

    <section className="final-action"><div className="page-width"><span>See the boundary in action</span><h2>See Sentinel make the decision.</h2><p>Run a protected checkout or simulate repeated card-testing behaviour through the real backend decision path.</p><div><Link className="primary-cta" to="/checkout">Try protected checkout <ArrowRight/></Link><Link className="secondary-cta" to="/checkout?demo=burst_attacker">Run attack simulation</Link><Link className="text-arrow" to="/results">View results <ArrowRight/></Link></div></div></section>
  </main>;
}
