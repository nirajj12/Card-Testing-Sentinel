import { ArrowRight, CheckCircle2, Eye, Fingerprint, Gauge, History, RefreshCcw, ShieldCheck, Shuffle, XCircle } from "lucide-react";
import { useReducedMotion } from "framer-motion";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { SignalCard } from "../components/SignalCard";
import { ACTIVE_FEATURE_COUNT } from "../data/publicEvidence";

type HeroMode = "normal" | "burst";
type OutcomeMode = "allow" | "review" | "block";
const burstSequence = [
  {
    title: "Small-value attempt",
    detail: "₹2 · first try",
  },
  {
    title: "Card reference changed",
    detail: "+4 seconds",
  },
  {
    title: "Another rapid retry",
    detail: "+7 seconds",
  },
] as const;
const normalSequence = [
  { title: "Checkout started", detail: "One familiar session" },
  { title: "One card selected", detail: "No switching" },
  { title: "Payment submitted", detail: "One careful attempt" },
] as const;
const outcomeStories = {
  allow: {
    label: "ALLOW",
    title: "A normal purchase continues",
    example: "A shopper pays ₹2,499 once from a consistent session.",
    evidence: "Normal pace · no repeated declines · stable context",
    result: "Sentinel permits order creation. Razorpay decides the payment later.",
  },
  review: {
    label: "REVIEW",
    title: "An uncertain pattern is held",
    example: "Several low-value retries appear, but the pattern is not yet conclusive.",
    evidence: "Rising velocity · one verified decline · limited history",
    result: "Sentinel holds the attempt. This prototype creates no Razorpay order.",
  },
  block: {
    label: "BLOCK",
    title: "A strong testing pattern stops",
    example: "Rapid low-value attempts continue while protected card references keep changing.",
    evidence: "Strong velocity · repeated declines · card switching",
    result: "Sentinel stops the attempt before any Razorpay order is created.",
  },
} as const;
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
  const [burstStage, setBurstStage] = useState(0);
  const [outcome, setOutcome] = useState<OutcomeMode>("allow");
  const reduceMotion = useReducedMotion();
  const suspicious = mode === "burst";
  const events = suspicious ? burstSequence : normalSequence;
  const outcomeStory = outcomeStories[outcome];
  const OutcomeIcon = outcome === "allow" ? CheckCircle2 : outcome === "review" ? Eye : XCircle;

  useEffect(() => {
    if (!suspicious || reduceMotion) {
      setBurstStage(0);
      return;
    }
    const timer = window.setInterval(
      () => setBurstStage((current) => (current + 1) % burstSequence.length),
      1900,
    );
    return () => window.clearInterval(timer);
  }, [suspicious, reduceMotion]);

  return <main>
    <section className="home-hero page-width refined-hero">
      <div className="hero-copy"><span className="eyebrow-pill"><i/>Behavioural protection before authorization</span><h1>Stop card testing <em>before payment begins.</em></h1><p>Sentinel evaluates merchant-visible behaviour before a Razorpay order is created. It separates ordinary payment intent from repeated patterns that need intervention.</p><div className="hero-actions"><Link className="primary-cta" to="/checkout">Try protected checkout <ArrowRight/></Link><Link className="secondary-cta" to="/checkout?demo=burst_attacker">Run attack simulation</Link></div><p className="hero-disclaimer">Razorpay Test Mode · Synthetic scenarios · Sentinel never accepts or stores raw card credentials.</p></div>
      <div className={`hero-behavior-visual ${mode} stage-${burstStage}`} aria-label={`${suspicious ? "Suspicious burst" : "Normal purchase"} behavior story`}>
        <div className="behavior-visual-head">
          <div><span>Checkout behaviour</span><strong>{suspicious ? "A pattern forms in seconds" : "One ordinary purchase"}</strong></div>
          <div className="hero-mode-tabs" role="group" aria-label="Choose example behavior"><button type="button" className={!suspicious ? "active" : ""} aria-pressed={!suspicious} onClick={() => setMode("normal")}>Normal shopper</button><button type="button" className={suspicious ? "active" : ""} aria-pressed={suspicious} onClick={() => setMode("burst")}>Testing burst</button></div>
        </div>

        <div className="behavior-timeline">
          <div className="timeline-track" aria-hidden="true"><i/></div>
          {events.map((event, index) => <article className={`${!suspicious || index <= burstStage ? "reached" : ""} ${suspicious && index === burstStage ? "current" : ""}`} key={event.title}>
            <b>{String(index + 1).padStart(2, "0")}</b>
            <strong>{event.title}</strong>
            <small>{event.detail}</small>
          </article>)}
        </div>

        <div className="behavior-signals" aria-label="Signals Sentinel observes">
          {(suspicious ? ["Rapid pace", "Repeated declines", "Changing cards"] : ["Normal pace", "No decline pattern", "Stable context"]).map((signal) => <span key={signal}><i/>{signal}</span>)}
        </div>

        <div className="sentinel-gateway">
          <div className="gateway-mark"><span className="gateway-orbit"/><ShieldCheck/></div>
          <div className="gateway-copy"><span>Sentinel boundary</span><strong>Behaviour checked before Razorpay</strong><small>Protected references only — never raw card details</small></div>
          <ArrowRight className="gateway-arrow" aria-hidden="true"/>
          <div className="gateway-result">
            {suspicious ? <XCircle/> : <CheckCircle2/>}
            <div><span>{suspicious ? "Stopped early" : "Path available"}</span><strong>{suspicious ? "Stopped before Razorpay" : "Order path open"}</strong><small>{suspicious ? "No order is created" : "Payment can continue"}</small></div>
          </div>
        </div>
        <p className="hero-sequence-caption">Illustrative sequence — Replay decisions are runtime-scored and may rise or fall.</p>
      </div>
    </section>

    <section className="section-block page-width"><header className="section-heading compact"><div><span>Behavioural evidence</span><h2>Sentinel combines {ACTIVE_FEATURE_COUNT} merchant-visible behavioural signals.</h2></div><p>Six plain-language groups explain what those signals observe. Open a card to see a realistic example; essential meaning never depends on hover.</p></header><div className="signal-story-grid">{signalCards.map(([icon,title,copy,example]) => <SignalCard key={title} icon={icon} title={title} copy={copy} example={example}/>)}</div></section>

    <section className="section-block process-section"><div className="page-width"><header className="section-heading outcome-section-heading"><div><span>The boundary</span><h2>One decision before order creation.</h2><p>Choose an outcome to see what it means in a real checkout.</p></div><Link className="text-arrow" to="/how-it-works">See the complete How It Works page <ArrowRight/></Link></header>
      <div className="outcome-selector" role="group" aria-label="Choose a Sentinel outcome">
        <button type="button" className={`allow ${outcome === "allow" ? "active" : ""}`} aria-pressed={outcome === "allow"} onClick={() => setOutcome("allow")}><CheckCircle2/><span>ALLOW</span><strong>Normal purchase</strong></button>
        <button type="button" className={`review ${outcome === "review" ? "active" : ""}`} aria-pressed={outcome === "review"} onClick={() => setOutcome("review")}><Eye/><span>REVIEW</span><strong>Uncertain pattern</strong></button>
        <button type="button" className={`block ${outcome === "block" ? "active" : ""}`} aria-pressed={outcome === "block"} onClick={() => setOutcome("block")}><XCircle/><span>BLOCK</span><strong>Strong testing pattern</strong></button>
      </div>
      <article className={`outcome-explainer ${outcome}`}>
        <div className="outcome-story-lead"><OutcomeIcon/><div><span>{outcomeStory.label} example</span><h3>{outcomeStory.title}</h3><p>{outcomeStory.example}</p></div></div>
        <div className="outcome-fact"><span>What Sentinel sees</span><strong>{outcomeStory.evidence}</strong></div>
        <ArrowRight className="outcome-flow-arrow" aria-hidden="true"/>
        <div className="outcome-fact result"><span>What happens next</span><strong>{outcomeStory.result}</strong></div>
      </article>
    </div></section>

    <section className="final-action"><div className="page-width"><span>See the boundary in action</span><h2>See Sentinel make the decision.</h2><p>Run a protected checkout or simulate repeated card-testing behaviour through the real backend decision path.</p><div><Link className="primary-cta" to="/checkout">Try protected checkout <ArrowRight/></Link><Link className="secondary-cta" to="/checkout?demo=burst_attacker">Run attack simulation</Link><Link className="text-arrow" to="/results">View results <ArrowRight/></Link></div></div></section>
  </main>;
}
