import { AlertTriangle, ArrowUpRight, CircleCheck, FlaskConical } from "lucide-react";
import { motion } from "framer-motion";
import { useEffect, useState } from "react";
import { api, friendlyError } from "../lib/api";
import type { BlindMetrics } from "../types";

const percent = (value: number, digits = 1) => `${(value * 100).toFixed(digits)}%`;
const title = (value: string) => value.split("_").map((part) => part[0]?.toUpperCase() + part.slice(1)).join(" ");

export function EvidencePage() {
  const [metrics, setMetrics] = useState<BlindMetrics | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { api.blindMetrics<BlindMetrics>().then((result) => result.status === "available" ? setMetrics(result) : setError(result.reason || "Evaluation is unavailable")).catch((reason) => setError(friendlyError(reason))); }, []);
  return <main className="evidence-route page-width">
    <header className="evidence-hero"><div><span className="eyebrow-pill"><i/>Final frozen Blind v2</span><h1>Measured protection.<br/><em>Visible customer friction.</em></h1><p>Frozen synthetic evidence, including every failed operating target. This does not establish production fraud performance.</p></div><aside><FlaskConical/><span>Evaluation principle</span><strong>Intervention strength and legitimate-customer impact belong in the same view.</strong></aside></header>
    {error && <div className="evidence-error"><AlertTriangle/>{error}</div>}
    {!metrics && !error && <div className="evidence-loading"><i/>Loading the frozen benchmark artifact…</div>}
    {metrics && <>
      <div className="evidence-source"><span><CircleCheck/>Frozen source loaded · verdict {metrics.verdict}</span><code>{metrics.source}</code><small>{metrics.blind_version} · runtime {metrics.active_runtime_version} · {metrics.active_device_counts.attack} attack devices · {metrics.active_device_counts.legitimate} legitimate devices</small></div>
      <section className="metric-grid">{[
        ["Attack intervention", metrics.headline.attack_intervention_rate, "Reviewed or temporarily blocked", "blue"],
        ["Attack temporary blocks", metrics.headline.attack_block_rate, "Reached the block action", "navy"],
        ["Legitimate intervention", metrics.headline.legitimate_intervention_rate, "Customer-friction cost", "amber"],
        ["Legitimate blocks", metrics.headline.legitimate_block_rate, "Highest-cost false positives", "red"],
      ].map(([label, value, note, tone], index) => <motion.article key={String(label)} className={`metric-card ${tone}`} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: index * .06 }}><span>0{index + 1}</span><strong>{percent(Number(value))}</strong><h2>{label}</h2><p>{note}</p></motion.article>)}</section>
      <section className="metric-grid">{[
        ["PR-AUC", metrics.model_metrics.pr_auc, "Model ranking precision-recall"],
        ["ROC-AUC", metrics.model_metrics.roc_auc, "Model ranking discrimination"],
      ].map(([label, value, note]) => <article key={String(label)} className="metric-card navy"><strong>{Number(value).toFixed(6)}</strong><h2>{label}</h2><p>{note}</p></article>)}
        <article className="metric-card red"><strong>{metrics.verdict}</strong><h2>Final verdict</h2><p>Frozen after the one-time Blind v2 evaluation.</p></article>
        <article className="metric-card amber"><strong>{Object.values(metrics.operating_targets).filter((value) => value === "FAIL").length} FAIL</strong><h2>Operating targets</h2><p>{Object.entries(metrics.operating_targets).map(([name, result]) => `${title(name)}: ${result}`).join(" · ")}</p></article>
      </section>
      <section className="evidence-charts"><article className="evidence-chart-card"><div className="evidence-card-head"><div><span>Sequence sensitivity</span><h2>Detection by attempt</h2></div><small><i/>Attack devices</small></div><div className="detection-bars">{Object.entries(metrics.detection_by_attempt).map(([attempt, value]) => <div key={attempt}><span>By attempt {attempt}</span><div><i style={{ width: percent(value) }}/></div><strong>{percent(value, 0)}</strong></div>)}</div></article><article className="evidence-chart-card"><div className="evidence-card-head"><div><span>Behavior families</span><h2>Intervention concentrates unevenly</h2></div><small>Intervention rate</small></div><div className="family-bars">{[...metrics.scenario_metrics].sort((a,b) => b.intervention_rate-a.intervention_rate).slice(0,8).map((row) => <div key={row.scenario} className={row.population}><span>{title(row.scenario)}</span><div><i style={{ width: percent(row.intervention_rate) }}/></div><strong>{percent(row.intervention_rate,0)}</strong></div>)}</div></article></section>
      <section className="evaluation-insights"><header><span>What judges should understand</span><h2>The benchmark tells a useful, imperfect story.</h2></header><div><article><ArrowUpRight/><strong>New behavior can generalise</strong><p>Several attack families accumulate enough visible evidence for intervention.</p></article><article><AlertTriangle/><strong>Patient attacks remain difficult</strong><p>{metrics.limitations.hardest_attacks.map(title).join(" and ")} can avoid strong per-device accumulation.</p></article><article><AlertTriangle/><strong>Failure can resemble abuse</strong><p>{metrics.limitations.highest_friction.map(title).join(" and ")} create the highest legitimate friction.</p></article></div></section>
      <aside className="known-limitations"><div><AlertTriangle/><span>Known limitations</span><h2>Legitimate-friction targets failed.</h2></div><dl><div><dt>Hardest attack patterns</dt><dd>{metrics.limitations.hardest_attacks.map(title).join(" · ")}</dd></div><div><dt>Major failure families</dt><dd>{metrics.limitations.highest_friction.map(title).join(" · ")}</dd></div><div><dt>Blind replay</dt><dd>{title(metrics.replay.status)} — {metrics.replay.reason}</dd></div><div><dt>Historical evidence</dt><dd>{metrics.historical_evidence.version} remains historical and is not directly comparable to Blind v2.</dd></div></dl><p>{metrics.limitations.summary} {metrics.disclosure}</p></aside>
    </>}
  </main>;
}
