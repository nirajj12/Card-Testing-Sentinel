import {
  Activity,
  ArrowRight,
  CheckCircle2,
  CreditCard,
  Database,
  Gauge,
  GitBranch,
  History,
  KeyRound,
  LockKeyhole,
  Radar,
  RefreshCw,
  ShieldCheck,
  ShoppingCart,
  Smartphone,
  Store,
  Webhook,
  XCircle,
} from "lucide-react";
import { ACTIVE_FEATURE_COUNT } from "../data/publicEvidence";

const architecture = [
  [ShoppingCart, "Checkout intent", "Before a Razorpay order exists"],
  [Database, "Available context", "Current observables + trusted history"],
  [Activity, `${ACTIVE_FEATURE_COUNT} causal features`, "Pre-payment information only"],
  [Gauge, "Model v3.1", "Estimates behavioral risk"],
  [Radar, "Behavioral risk score", "A score, not an action"],
  [GitBranch, "Policy v2", "Chooses the intervention"],
] as const;

const feedbackSteps = [
  [ShieldCheck, "Sentinel ALLOW"],
  [Store, "Razorpay order"],
  [CreditCard, "Razorpay Checkout"],
  [CheckCircle2, "Payment processed"],
  [Webhook, "Signed webhook"],
  [History, "Trusted future history"],
] as const;

export function HowItWorksPage() {
  return (
    <main className="how-page compact-how-page">
      <section className="how-system page-width" aria-labelledby="how-title">
        <header className="how-intro">
          <span className="eyebrow-pill"><i />Pre-authorization protection</span>
          <h1 id="how-title">How Sentinel works <em>before payment.</em></h1>
          <p>Checkout behavior is evaluated before a Razorpay order exists.</p>
        </header>

        <div className="system-flow-shell">
          <div className="compact-section-title">
            <span>System flow</span>
            <p>Current merchant-visible context and previously trusted history enter the same live scoring path.</p>
          </div>
          <ol className="compact-system-flow" aria-label="Sentinel pre-authorization flow">
            {architecture.map(([Icon, label, detail], index) => (
              <li className="how-hover-card" key={label}>
                <Icon aria-hidden="true" />
                <strong>{label}</strong>
                <small>{detail}</small>
                {index < architecture.length - 1 && <ArrowRight className="flow-arrow" aria-hidden="true" />}
              </li>
            ))}
          </ol>
          <div className="compact-policy-output" aria-label="Policy v2 actions">
            <span>Policy action</span>
            <strong className="allow">ALLOW</strong>
            <strong className="review">REVIEW</strong>
            <strong className="block">BLOCK</strong>
          </div>
        </div>
      </section>

      <section className="compact-decision-section">
        <div className="page-width">
          <header className="compact-heading inverse">
            <span>Three bounded actions</span>
            <h2>The model scores risk. Policy chooses the action.</h2>
          </header>
          <div className="compact-decisions">
            <article className="how-hover-card allow">
              <CheckCircle2 aria-hidden="true" />
              <div><h3>ALLOW</h3><p>Sentinel permits Razorpay order creation.</p></div>
              <strong>ALLOW does not mean payment approved.</strong>
            </article>
            <article className="how-hover-card review">
              <LockKeyhole aria-hidden="true" />
              <div><h3>REVIEW</h3><p>Elevated risk. The payment path is suppressed.</p></div>
              <strong>An automated Sentinel state—not human review.</strong>
            </article>
            <article className="how-hover-card block">
              <XCircle aria-hidden="true" />
              <div><h3>BLOCK</h3><p>Supporting behavioral evidence is strong enough to suppress this attempt.</p></div>
              <strong>No Razorpay order is created.</strong>
            </article>
          </div>
        </div>
      </section>

      <section className="compact-causal page-width" aria-labelledby="causal-heading">
        <header className="compact-heading">
          <span>The causal boundary</span>
          <h2 id="causal-heading">What exists when Sentinel decides?</h2>
        </header>
        <div className="compact-causal-grid">
          <article className="how-hover-card known-card">
            <ShieldCheck aria-hidden="true" />
            <div><h3>Known at precheck</h3><p>Amount, merchant, device, session, IP reference, available customer identifier, timing context and trusted prior history.</p></div>
          </article>
          <div className="causal-divider" aria-hidden="true"><span>Decision boundary</span></div>
          <article className="how-hover-card unknown-card">
            <KeyRound aria-hidden="true" />
            <div><h3>Not known yet</h3><p>The current card, current card last4 or network, current payment result and current Razorpay outcome.</p></div>
          </article>
        </div>
        <p className="compact-causal-rule"><strong>The current card and current payment result cannot affect their own current risk decision.</strong> A later verified outcome may inform future attempts.</p>
      </section>

      <section className="compact-behavior-section">
        <div className="page-width">
          <header className="compact-heading">
            <span>Signals in context</span>
            <h2>Suspicion can start now. Evidence evolves later.</h2>
          </header>
          <div className="behavior-cards">
            <article className="how-hover-card risk-card">
              <Gauge aria-hidden="true" />
              <h3>A strong signal can be suspicious immediately.</h3>
              <p>A micro-value checkout may already produce elevated model risk. High risk does not automatically mean BLOCK; Policy v2 looks for supporting behavioral evidence.</p>
              <strong>Later attempts use the history that genuinely exists, so risk may rise or fall.</strong>
            </article>
            <article className="how-hover-card retry-card">
              <Smartphone aria-hidden="true" />
              <h3>Payment failure alone is not card testing.</h3>
              <p>A genuine customer may experience declines and retries. When surrounding behavior remains normal, Sentinel may continue to ALLOW.</p>
              <strong>Failures matter in context, not in isolation.</strong>
            </article>
          </div>
          <div className="classifier-strip" aria-label="Traditional fraud classifier compared with Sentinel">
            <RefreshCw aria-hidden="true" />
            <div><span>Traditional fraud classifier</span><strong>Payment exists → features → fraud prediction</strong></div>
            <ArrowRight aria-hidden="true" />
            <div><span>Sentinel pre-authorization</span><strong>Checkout intent → behavioral precheck → policy action → Razorpay order only if Sentinel returns ALLOW</strong></div>
          </div>
        </div>
      </section>

      <section className="compact-feedback-section">
        <div className="page-width">
          <header className="compact-heading inverse">
            <span>Trusted outcome loop</span>
            <h2>Verified outcomes become future context.</h2>
            <p>A browser callback is not authoritative. A verified signed Razorpay webhook is.</p>
          </header>
          <ol className="compact-feedback-flow" aria-label="Trusted payment outcome feedback loop">
            {feedbackSteps.map(([Icon, label], index) => (
              <li className="how-hover-card" key={label}>
                <Icon aria-hidden="true" /><strong>{label}</strong>
                {index < feedbackSteps.length - 1 && <ArrowRight aria-hidden="true" />}
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section className="compact-proof page-width" aria-labelledby="proof-heading">
        <header className="compact-heading">
          <span>Three proof layers</span>
          <h2 id="proof-heading">Each view answers a different question.</h2>
        </header>
        <div className="compact-proof-grid">
          <article className="how-hover-card"><CreditCard aria-hidden="true" /><div><h3>Protected Checkout</h3><p>Real Razorpay Test Mode integration.</p></div></article>
          <article className="how-hover-card"><Activity aria-hidden="true" /><div><h3>Replay Lab</h3><p>Controlled synthetic behavior through the real scoring runtime. Decisions are runtime-generated, not predefined; replay is not Razorpay traffic.</p></div></article>
          <article className="how-hover-card"><Gauge aria-hidden="true" /><div><h3>Evaluation</h3><p>Aggregate ML evidence.</p></div></article>
        </div>
        <p className="compact-prototype-status">Evaluated prototype <i /> production_ready = false <i /> PBRSS = MIXED</p>
      </section>
    </main>
  );
}
