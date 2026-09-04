import { ArrowRight, DatabaseZap, ShieldCheck } from "lucide-react";
import { Link } from "react-router-dom";
import { ArchitectureFlow } from "../components/how-it-works/ArchitectureFlow";
import { CausalBoundary, TrustedOutcomeLoop } from "../components/how-it-works/SupportingSections";

export function HowItWorksPage() {
  return (
    <main className="hiw-page">
      <section className="hiw-hero page-width" aria-labelledby="how-title">
        <span className="eyebrow-pill"><ShieldCheck aria-hidden="true" />How it works</span>
        <h1 id="how-title">How Sentinel decides<br /><em>before order creation.</em></h1>
        <p>Follow one checkout from the information a merchant can already see to the action Sentinel takes next.</p>
      </section>

      <ArchitectureFlow />
      <CausalBoundary />
      <TrustedOutcomeLoop />

      <section className="hiw-cta">
        <div className="page-width">
          <div className="hiw-cta-mark" aria-hidden="true"><DatabaseZap /></div>
          <div><span>Try the real flow</span><h2>Test the decision path yourself.</h2><p>Run a protected checkout and inspect its risk signals, policy action, and payment lifecycle.</p></div>
          <Link className="primary-cta" to="/checkout">Try Protected Checkout <ArrowRight aria-hidden="true" /></Link>
        </div>
      </section>
    </main>
  );
}
