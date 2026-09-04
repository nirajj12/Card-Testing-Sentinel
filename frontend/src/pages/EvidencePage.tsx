import {
  Activity,
  ArrowUpRight,
  CheckCircle2,
  Clock3,
  FlaskConical,
  Gauge,
  ShieldAlert,
  ShieldCheck,
} from "lucide-react";
import { EvaluationCharts } from "../components/EvaluationCharts";
import { formatPercent, publicEvidence } from "../data/publicEvidence";

const githubUrl = "https://github.com/nirajj12/Card-Testing-Sentinel";

export function EvidencePage() {
  const { evaluation, quality, runtime, economics } = publicEvidence;
  const headlineMetrics = [
    {
      value: formatPercent(evaluation.attackRecallPct),
      label: "Attack recall (REVIEW+)",
      note: "Attack profiles that reached REVIEW or BLOCK",
      tone: "positive",
    },
    {
      value: formatPercent(evaluation.interventionPrecisionPct),
      label: "Intervention precision (REVIEW+)",
      note: "Interrupted profiles that were attack profiles",
      tone: "positive",
    },
    {
      value: formatPercent(evaluation.legitimateInterventionPct, 2),
      label: "Legitimate profiles interrupted",
      note: "Genuine-profile friction that needs improvement",
      tone: "warning",
    },
    {
      value: formatPercent(evaluation.legitimateBlockPct, 2),
      label: "Legitimate profiles hard-blocked",
      note: "Genuine profiles stopped before order creation",
      tone: "neutral",
    },
  ];

  return (
    <main className="results-page polished-results">
      <header className="results-hero-v2 page-width">
        <div>
          <span className="eyebrow-pill"><i />Synthetic stress evaluation</span>
          <h1>Current evaluation results</h1>
          <p>Sentinel surfaced 96.4% of attack profiles in a shifted synthetic stress evaluation. Its main limitation was customer friction on retry-heavy ordinary checkout traffic.</p>
        </div>
        <aside>
          <FlaskConical />
          <p><strong>Profile-level results</strong>One profile represents a synthetic device&apos;s behavior across multiple payment attempts.</p>
        </aside>
      </header>

      <aside className="evidence-scope page-width" aria-label="Evaluation evidence scope">
        <strong>Evidence scope</strong><span>Frozen PBRSS-v1 shifted stress</span><i /><span>Development validation reported separately</span><i /><span>Conclusion: MIXED</span><i /><span>production_ready=false</span>
      </aside>

      <section className="results-overview page-width" aria-labelledby="overview-title">
        <header className="results-section-heading">
          <span>Buildathon metrics at a glance</span>
          <h2 id="overview-title">Coverage, precision, and customer impact</h2>
        </header>
        <div className="results-metric-grid">
          {headlineMetrics.map((metric) => (
            <article className={metric.tone} key={metric.label}>
              <strong>{metric.value}</strong>
              <h3>{metric.label}</h3>
              <p>{metric.note}</p>
            </article>
          ))}
        </div>
        <div className="review-definition">
          <ShieldCheck />
          <p><strong>What REVIEW+ means</strong>REVIEW+ is the intervention class: REVIEW or BLOCK. REVIEW suppresses local order creation for this attempt; it is not a Razorpay manual-review or authentication flow.</p>
        </div>
      </section>

      <EvaluationCharts />

      <section className="results-learning">
        <div className="page-width learning-panels">
          <article className="worked-panel">
            <span><CheckCircle2 />What worked</span>
            <h2>Repeated attack behavior became visible.</h2>
            <ul>
              <li>High REVIEW+ coverage across all three attack stress families</li>
              <li>92.16% cumulative attack coverage by attempt 3</li>
              <li>Only 0.16% of legitimate profiles reached hard BLOCK</li>
              <li>Razorpay order creation remains behind the ALLOW boundary</li>
            </ul>
          </article>
          <article className="improve-panel">
            <span><ShieldAlert />What needs improvement</span>
            <h2>Customer friction remains too high.</h2>
            <ul>
              <li>20.72% overall legitimate REVIEW+ friction</li>
              <li>Ordinary checkout reached 25.3% intervention</li>
              <li>Early attack attempts are harder before history accumulates</li>
              <li>Calibration weakened under shifted stress traffic</li>
            </ul>
          </article>
        </div>
      </section>

      <section className="testing-method page-width" aria-labelledby="testing-title">
        <header className="results-section-heading">
          <span>Evaluation method</span>
          <h2 id="testing-title">How we tested Sentinel</h2>
          <p>Difficult attacks and genuine look-alikes were evaluated after the detector and decision thresholds were frozen.</p>
        </header>
        <div className="method-stat-grid">
          {[
            [evaluation.totalProfiles, "synthetic device profiles"],
            [evaluation.attackProfiles, "attack profiles"],
            [evaluation.legitimateProfiles, "legitimate profiles"],
            [evaluation.syntheticMerchants, "synthetic merchants"],
          ].map(([value, label]) => (
            <article key={label}><strong>{Number(value).toLocaleString("en-IN")}</strong><span>{label}</span></article>
          ))}
        </div>
        <ul className="method-principles">
          <li>Difficult attack and genuine look-alike scenarios</li>
          <li>Detector frozen before the final stress evaluation</li>
          <li>One frozen evaluation result preserved</li>
          <li>No post-test detector or threshold tuning</li>
          <li>Synthetic results are not production Razorpay performance</li>
        </ul>
      </section>

      <section className="technical-evidence">
        <div className="page-width">
          <header className="results-section-heading inverse">
            <span>For evaluators</span>
            <h2>Technical evidence</h2>
            <p>Attack coverage remained useful, but discrimination and calibration weakened under the shifted stress suite.</p>
          </header>
          <div className="quality-grid">
            {[
              ["PR-AUC", quality.prAuc.toFixed(3), "Higher is better"],
              ["ROC-AUC", quality.rocAuc.toFixed(3), "Higher is better"],
              ["Brier", quality.brier.toFixed(3), "Lower is better"],
              ["Calibration error (ECE)", quality.ece.toFixed(3), "Lower is better"],
            ].map(([label, value, note]) => (
              <article key={label}><span>{label}</span><strong>{value}</strong><small>{note}</small></article>
            ))}
          </div>
          <div className="runtime-evidence">
            <article><Gauge /><span>Local prototype benchmark</span><strong>p50 {runtime.p50Ms.toFixed(1)} ms</strong><small>p95 {runtime.p95Ms.toFixed(1)} ms</small></article>
            <article><Activity /><span>Sequential local run</span><strong>{runtime.requests} requests</strong><small>{runtime.errors} errors</small></article>
            <article><ShieldCheck /><span>Razorpay Test Mode verified</span><strong>ALLOW created a test order</strong><small>REVIEW and BLOCK stopped before order creation</small></article>
            <article><Clock3 /><span>Outcome integrity</span><strong>Signed response handling</strong><small>Signed webhook handling verified locally.</small></article>
          </div>
          <p className="runtime-disclaimer">Local non-production latency; not production Razorpay latency.</p>
          <a className="evidence-link" href={githubUrl} target="_blank" rel="noreferrer">View technical evidence on GitHub <ArrowUpRight /></a>
        </div>
      </section>

      <section className="economic-context page-width" aria-labelledby="economic-title">
        <header className="results-section-heading">
          <span>Illustrative context</span>
          <h2 id="economic-title">Merchant context changes the trade-off</h2>
          <p>The same fraud-control operating point can be too expensive during quiet traffic but useful during an active card-testing campaign.</p>
        </header>
        <div className="economics-grid">
          {economics.map((scenario) => {
            const positive = scenario.netValueInr >= 0;
            return (
              <article className={positive ? "positive" : "negative"} key={scenario.name}>
                <span>{scenario.name}</span>
                <strong>{positive ? "+" : "−"}INR {(Math.abs(scenario.netValueInr) / 1_000_000).toFixed(2)}M</strong>
                <small>Estimated net illustrative value</small>
              </article>
            );
          })}
        </div>
        <p className="economics-disclaimer">Illustrative merchant assumptions only. These are not measured Razorpay economics, observed savings, or production loss estimates.</p>
      </section>

      <section className="current-limitation page-width">
        <ShieldAlert />
        <div>
          <span>Current limitation</span>
          <h2>Strong attack coverage is not enough for a general production rollout.</h2>
          <p>The detector has strong attack coverage in the synthetic stress suite, but 20.72% legitimate REVIEW+ friction is too high. Future work should reduce genuine retry friction and validate the next operating policy on a new untouched evaluation source.</p>
        </div>
      </section>
    </main>
  );
}
