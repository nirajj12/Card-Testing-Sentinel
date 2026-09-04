import { ChevronLeft, FlaskConical, Pause, Play, RotateCcw, StepForward, X } from "lucide-react";
import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useRef, useState } from "react";
import { evidenceLabels, presentReason } from "../features/decision";
import { api, friendlyError } from "../lib/api";
import type { ActivityAttempt, Operation, SystemStatus } from "../types";

type Scenario = { id: string; label: string; attempts: number };
type DemoStart = { demo_id: string; total_attempts: number };
type DemoAttempt = {
  attempt: number;
  amount: number;
  currency: string;
  campaign_active: boolean;
  timestamp: string;
  elapsed_seconds: number;
};
type DemoStep = {
  complete: boolean;
  attempt?: DemoAttempt;
  operations?: Operation;
  timeline?: Array<Record<string, unknown>>;
};

type ScenarioPresentation = {
  label: string;
  description: string;
  group: "legitimate" | "suspicious";
};

const scenarioPresentations: Record<string, ScenarioPresentation> = {
  normal_customer: { label: "Everyday Checkout", description: "Normal checkout behavior with one transient same-card retry.", group: "legitimate" },
  normal_bad_luck: { label: "Genuine Retry", description: "Several legitimate declines followed by a successful retry.", group: "legitimate" },
  flash_standard: { label: "Flash Sale", description: "Fast but legitimate retries during a merchant campaign.", group: "legitimate" },
  flash_hard_retry: { label: "Flash-Sale Hard Retry", description: "A difficult legitimate campaign retry pattern near the risk boundary.", group: "legitimate" },
  burst_attacker: { label: "Burst Card Testing", description: "Rapid micro-value probing with repeated suspicious behavior.", group: "suspicious" },
  evasive_attacker: { label: "Evasive Card Testing", description: "Slower suspicious activity designed to avoid simple velocity rules.", group: "suspicious" },
  patient_attacker: { label: "Patient Card Testing", description: "Low-and-slow suspicious activity spread across longer intervals.", group: "suspicious" },
};

function scoreText(score: number | null) {
  return score === null ? "Unavailable" : `${(score * 100).toFixed(1)} / 100`;
}

function deltaText(current: number | null, previous: number | null | undefined) {
  if (current === null || previous === null || previous === undefined) return null;
  const delta = (current - previous) * 100;
  if (Math.abs(delta) < 0.05) return "→ 0.0";
  return delta > 0 ? `↑ +${delta.toFixed(1)}` : `↓ ${delta.toFixed(1)}`;
}

function amountText(amount: number, currency: string) {
  return new Intl.NumberFormat("en-IN", { style: "currency", currency, maximumFractionDigits: Number.isInteger(amount) ? 0 : 2 }).format(amount);
}

function elapsedText(seconds: number | undefined) {
  if (seconds === undefined) return "Unavailable";
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
  if (seconds < 86400) return `${(seconds / 3600).toFixed(seconds % 3600 ? 1 : 0)}h`;
  return `${(seconds / 86400).toFixed(1)}d`;
}

function actionCopy(operation: Operation) {
  if (operation.decision === "allow") return "Sentinel permits the simulated payment path to continue. Payment approval is determined later by the simulated outcome.";
  if (operation.decision === "review") {
    return operation.reason_codes.includes("block_withheld_insufficient_evidence")
      ? "Elevated risk. Payment path suppressed. Policy did not have enough corroborating evidence for automatic BLOCK."
      : "Elevated risk. Payment path suppressed for this attempt before payment.";
  }
  return "Corroborating behavioral evidence was strong enough to suppress this attempt before payment.";
}

function lifecycleValue(operation: Operation, field: "outcome_status" | "checkout_status") {
  const value = operation[field];
  if (value) return value.toUpperCase();
  return operation.authorization === "suppressed" ? "NOT CREATED" : field === "checkout_status" ? "NOT COMPLETED" : "NOT RECORDED";
}

export function ReplayDrawer({ open, onClose, onAttempt, system, initialScenario }: { open: boolean; onClose: () => void; onAttempt: (attempt: ActivityAttempt) => void; system: SystemStatus | null; initialScenario?: string }) {
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [selected, setSelected] = useState("normal_customer");
  const [demoId, setDemoId] = useState<string | null>(null);
  const [total, setTotal] = useState(0);
  const [steps, setSteps] = useState<ActivityAttempt[]>([]);
  const [cursor, setCursor] = useState(-1);
  const [complete, setComplete] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("Select a scenario. Decisions are not predefined.");
  const playingRef = useRef(false);
  const closeRef = useRef<HTMLButtonElement>(null);
  const previousFocus = useRef<HTMLElement | null>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  function closeDialog() {
    const returnTarget = previousFocus.current;
    onCloseRef.current();
    window.setTimeout(() => returnTarget?.focus(), 0);
  }

  useEffect(() => {
    if (!open) return;
    previousFocus.current = document.activeElement as HTMLElement;
    const timer = window.setTimeout(() => closeRef.current?.focus(), 50);
    function escape(event: KeyboardEvent) { if (event.key === "Escape") closeDialog(); }
    document.addEventListener("keydown", escape);
    return () => { window.clearTimeout(timer); document.removeEventListener("keydown", escape); };
  }, [open]);

  useEffect(() => { if (initialScenario && scenarioPresentations[initialScenario]) setSelected(initialScenario); }, [initialScenario]);
  useEffect(() => {
    if (open && !scenarios.length) api.demoScenarios<{ items: Scenario[] }>().then((data) => setScenarios(data.items)).catch((error) => setMessage(friendlyError(error)));
  }, [open, scenarios.length]);

  async function start() {
    playingRef.current = false; setPlaying(false); setBusy(true);
    try {
      const result = await api.demoStart<DemoStart>(selected);
      setDemoId(result.demo_id); setTotal(result.total_attempts); setSteps([]); setCursor(-1); setComplete(false); setMessage("Scenario ready. Run the first backend-scored attempt.");
    } catch (error) { setMessage(friendlyError(error)); }
    finally { setBusy(false); }
  }

  async function advance(id: string): Promise<boolean> {
    setBusy(true);
    try {
      const result = await api.demoStep<DemoStep>(id);
      if (!result.operations || !result.attempt) { setComplete(true); return false; }
      const item: ActivityAttempt = {
        id: `replay-${id}-${result.attempt.attempt}`,
        attempt: result.attempt.attempt,
        amount: result.attempt.amount,
        currency: result.attempt.currency,
        timestamp: result.attempt.timestamp,
        elapsed_seconds: result.attempt.elapsed_seconds,
        campaign_active: result.attempt.campaign_active,
        source: "replay",
        operation: result.operations,
      };
      setSteps((current) => { setCursor(current.length); return [...current, item]; });
      setComplete(result.complete); onAttempt(item);
      setMessage(`${scenarioPresentations[selected]?.label || selected} · backend returned ${result.operations.decision.toUpperCase()}`);
      return !result.complete;
    } catch (error) { setMessage(friendlyError(error)); return false; }
    finally { setBusy(false); }
  }

  async function next(): Promise<boolean> {
    if (cursor < steps.length - 1) { setCursor(cursor + 1); return true; }
    if (!demoId || complete) return false;
    return advance(demoId);
  }

  async function togglePlay() {
    if (playingRef.current) { playingRef.current = false; setPlaying(false); return; }
    if (!demoId || complete) return;
    playingRef.current = true; setPlaying(true);
    let more = true;
    while (playingRef.current && more) { more = await advance(demoId); if (more) await new Promise((resolve) => window.setTimeout(resolve, 900)); }
    playingRef.current = false; setPlaying(false);
  }

  async function reset() {
    playingRef.current = false; setPlaying(false); setBusy(true);
    try {
      await api.demoReset<{ reset: boolean }>();
      setDemoId(null); setTotal(0); setSteps([]); setCursor(-1); setComplete(false); setMessage("Demo reset. Choose a supported scenario to begin again.");
    } catch (error) { setMessage(friendlyError(error)); }
    finally { setBusy(false); }
  }

  function scenarioButtons(group: ScenarioPresentation["group"]) {
    return scenarios.filter((scenario) => scenarioPresentations[scenario.id]?.group === group).map((scenario) => {
      const presentation = scenarioPresentations[scenario.id];
      return <button key={scenario.id} className={selected === scenario.id ? "active" : ""} type="button" aria-pressed={selected === scenario.id} disabled={Boolean(demoId) || busy} onClick={() => setSelected(scenario.id)}>
        <FlaskConical size={16}/><span><strong>{presentation.label}</strong><small>{presentation.description}</small></span><b>{scenario.attempts}</b>
      </button>;
    });
  }

  const active = cursor >= 0 ? steps[cursor] : null;
  const previous = cursor > 0 ? steps[cursor - 1] : null;
  const riskDelta = active ? deltaText(active.operation.risk_score, previous?.operation.risk_score) : null;
  const evidence = active ? Object.entries(active.operation.evidence || {}).filter(([key]) => key in evidenceLabels) : [];
  const changedEvidence = active && previous ? evidence.filter(([key, value]) => previous.operation.evidence?.[key] !== value) : [];

  return <AnimatePresence>{open && <>
    <motion.button className="drawer-backdrop" onClick={closeDialog} aria-label="Close Sentinel Demo" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}/>
    <motion.aside className="replay-drawer" role="dialog" aria-modal="true" aria-labelledby="replay-title" initial={{ x: "100%" }} animate={{ x: 0 }} exit={{ x: "100%" }}>
      <div className="drawer-head"><div><span>Controlled simulation</span><h2 id="replay-title">Replay Lab</h2></div><button ref={closeRef} type="button" onClick={closeDialog} aria-label="Close replay dialog"><X/></button></div>
      <aside className="replay-authenticity"><strong>Runtime-scored, not scripted decisions</strong><p>Replay Lab generates controlled behavior, but ALLOW / REVIEW / BLOCK is not predefined. Each attempt uses the same RiskService, FeatureEngineV3, Model v3.1, Policy v2 and state path as live prechecks.</p><small>Replay uses simulated lifecycle events, not Razorpay traffic.</small></aside>

      <div className="scenario-groups"><span>Legitimate customer behavior</span><div className="scenario-grid">{scenarioButtons("legitimate")}</div><span>Suspicious behavior</span><div className="scenario-grid">{scenarioButtons("suspicious")}</div>{system?.model_status === "degraded_rules_only" && <p className="demo-notice">The model is unavailable; this run will use the published fallback rules.</p>}</div>
      <p className="genuine-contrast"><strong>Compare with Genuine Retry:</strong> several payment declines can remain ALLOW when the surrounding behavior stays normal.</p>
      <button className="primary-cta full" type="button" onClick={start} disabled={busy || Boolean(demoId)}>Start selected scenario <span>→</span></button>

      <div className="replay-progress"><div><span>Selected attempt</span><strong>{active?.attempt || 0} / {total || "—"}</strong></div><div className="timeline"><i style={{ width: total ? `${((active?.attempt || 0) / total) * 100}%` : "0%" }}/></div></div>
      {steps.length > 0 && <ol className="replay-timeline" aria-label="Scenario attempts">{steps.map((item, index) => <li key={item.id}><button type="button" className={index === cursor ? "active" : ""} aria-pressed={index === cursor} aria-label={`Inspect attempt ${item.attempt}, ${item.operation.decision}`} onClick={() => setCursor(index)}><b>{item.attempt}</b><span>{item.operation.decision.toUpperCase()}<small>{scoreText(item.operation.risk_score)}</small></span><i>{index === 0 ? "Start" : deltaText(item.operation.risk_score, steps[index - 1].operation.risk_score)}</i></button></li>)}</ol>}

      {active ? <div className="replay-detail">
        <section className="replay-decision-first" aria-label="Selected attempt decision"><div><span>Policy action</span><strong className={`activity-decision ${active.operation.decision}`}>{active.operation.decision.toUpperCase()}</strong></div><div><span>Model risk</span><strong>{scoreText(active.operation.risk_score)}</strong></div><div><span>Risk delta</span><strong className={riskDelta?.startsWith("↑") ? "delta-up" : riskDelta?.startsWith("↓") ? "delta-down" : ""}>{riskDelta || "No previous attempt"}</strong></div><p>Each attempt is rescored from the history that genuinely existed before it. Risk may rise or fall.</p></section>

        {active.attempt === 1 && active.operation.decision === "review" && active.amount <= 10 && <aside className="initial-review-note"><strong>Initial suspicious signal</strong><p>Micro-value checkout behavior at {amountText(active.amount, active.currency)} raised the model risk. {active.operation.reason_codes.includes("block_withheld_insufficient_evidence") ? "Policy withheld automatic blocking because stronger corroborating history was not yet available." : "The displayed history contains no prior verified failures or decline streak."}</p></aside>}

        <section className="replay-detail-section"><span>Current attempt</span><dl className="replay-facts"><div><dt>Amount</dt><dd>{amountText(active.amount, active.currency)}</dd></div><div><dt>Currency</dt><dd>{active.currency}</dd></div><div><dt>Elapsed scenario time</dt><dd>{elapsedText(active.elapsed_seconds)}</dd></div><div><dt>Merchant campaign</dt><dd>{active.campaign_active ? "ACTIVE" : "NO"}</dd></div></dl><small>Current card details are not available to the precheck.</small></section>
        <section className="replay-detail-section"><span>Behavioral history</span>{evidence.length ? <dl className="replay-facts">{evidence.map(([key, value]) => <div key={key}><dt>{evidenceLabels[key]}</dt><dd>{value}</dd></div>)}</dl> : <p className="empty-evidence">No safe evidence snapshot is available for this attempt.</p>}</section>
        <section className="replay-detail-section"><span>What changed?</span>{!previous ? <p className="empty-evidence">No previous attempt.</p> : changedEvidence.length ? <dl className="replay-changes">{changedEvidence.map(([key, value]) => <div key={key}><dt>{evidenceLabels[key]}</dt><dd><s>{previous.operation.evidence?.[key]}</s><b>→</b><strong>{value}</strong></dd></div>)}</dl> : <p className="empty-evidence">No major tracked evidence changed since the previous attempt.</p>}<small>Observed changes are context, not model attribution.</small></section>
        <section className="replay-detail-section"><span>Supporting policy evidence</span>{active.operation.reason_codes.length ? <div className="replay-reasons">{active.operation.reason_codes.map((code) => { const reason = presentReason(code); return <article key={code}><strong>{reason.label}</strong><p>{reason.explanation}</p></article>; })}</div> : <p className="empty-evidence">Policy v2 returned no elevated-action reason for this attempt.</p>}</section>
        <section className="replay-detail-section"><span>Sentinel action</span><p className="action-callout">{actionCopy(active.operation)}</p></section>
        <section className="replay-detail-section"><span>Simulation lifecycle</span><dl className="replay-facts"><div><dt>Authorization</dt><dd>{active.operation.authorization?.toUpperCase() || "UNAVAILABLE"}</dd></div><div><dt>Simulated outcome</dt><dd>{lifecycleValue(active.operation, "outcome_status")}</dd></div><div><dt>Checkout</dt><dd>{lifecycleValue(active.operation, "checkout_status")}</dd></div></dl><small>ALLOW permits continuation; it does not mean the payment was approved.</small></section>
        <section className="replay-audit"><span>Audit reference</span><code>{active.operation.protected_reference || "Protected reference unavailable"}</code><small>Replay explains one sequence. Aggregate performance is reported separately in Evaluation.</small></section>
      </div> : <div className="replay-result"><p>{message}</p></div>}

      <div className="replay-controls"><button type="button" disabled={busy || cursor <= 0} onClick={() => setCursor(cursor - 1)}><ChevronLeft/>Previous</button><button type="button" disabled={(!playing && busy) || !demoId || complete} onClick={togglePlay}>{playing ? <Pause/> : <Play/>}{playing ? "Pause" : "Play"}</button><button type="button" disabled={busy || !demoId || (complete && cursor >= steps.length - 1)} onClick={next}>Next<StepForward/></button></div>
      <p className="replay-message" aria-live="polite">{message}</p>
      <button className="reset-demo" type="button" onClick={reset} disabled={busy}><RotateCcw/>Reset demo</button>
    </motion.aside>
  </>}</AnimatePresence>;
}
