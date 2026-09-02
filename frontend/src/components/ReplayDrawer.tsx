import { ChevronLeft, FlaskConical, Pause, Play, RotateCcw, StepForward, X } from "lucide-react";
import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useRef, useState } from "react";
import { api, friendlyError } from "../lib/api";
import { decisionCopy } from "../features/decision";
import type { ActivityAttempt, Operation, SystemStatus } from "../types";

type Scenario = { id: string };
type DemoStart = { demo_id: string; total_attempts: number };
type DemoStep = { complete: boolean; attempt?: { attempt: number; amount: number; currency?: string; timestamp?: string }; operations?: Operation };

const scenarioLabels: Record<string, string> = { normal_customer: "Normal Purchase", normal_bad_luck: "Genuine Retry", burst_attacker: "Rapid Attack", patient_attacker: "Patient Attack" };

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
  const [message, setMessage] = useState("Select a scenario. Outcomes are not preloaded.");
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
    function escape(event: KeyboardEvent) {
      if (event.key === "Escape") {
        const returnTarget = previousFocus.current;
        onCloseRef.current();
        window.setTimeout(() => returnTarget?.focus(), 0);
      }
    }
    document.addEventListener("keydown", escape);
    return () => { window.clearTimeout(timer); document.removeEventListener("keydown", escape); };
  }, [open]);
  useEffect(() => { if (initialScenario && scenarioLabels[initialScenario]) setSelected(initialScenario); }, [initialScenario]);
  useEffect(() => { if (open && !scenarios.length) api.demoScenarios<{ items: Scenario[] }>().then((data) => setScenarios(data.items)).catch((error) => setMessage(friendlyError(error))); }, [open, scenarios.length]);

  async function start() {
    playingRef.current = false;
    setPlaying(false);
    setBusy(true);
    try {
      const result = await api.demoStart<DemoStart>(selected);
      setDemoId(result.demo_id); setTotal(result.total_attempts); setSteps([]); setCursor(-1); setComplete(false); setMessage("Scenario ready. Run the first real backend step.");
    } catch (error) { setMessage(friendlyError(error)); }
    finally { setBusy(false); }
  }

  async function advance(id: string): Promise<boolean> {
    setBusy(true);
    try {
      const result = await api.demoStep<DemoStep>(id);
      if (!result.operations || !result.attempt) { setComplete(true); return false; }
      const item: ActivityAttempt = { id: `replay-${id}-${result.attempt.attempt}`, attempt: result.attempt.attempt, amount: result.attempt.amount, currency: result.attempt.currency || "INR", timestamp: result.attempt.timestamp, source: "replay", operation: result.operations };
      setSteps((current) => { setCursor(current.length); return [...current, item]; });
      setComplete(result.complete); onAttempt(item); setMessage(`${scenarioLabels[selected]} · backend returned ${result.operations.decision.toUpperCase()}`); return !result.complete;
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
    try { await api.demoReset<{ reset: boolean }>(); setDemoId(null); setTotal(0); setSteps([]); setCursor(-1); setComplete(false); setMessage("Demo reset. Choose a supported scenario to begin again."); }
    catch (error) { setMessage(friendlyError(error)); }
    finally { setBusy(false); }
  }

  const active = cursor >= 0 ? steps[cursor] : null;
  return <AnimatePresence>{open && <><motion.button className="drawer-backdrop" onClick={closeDialog} aria-label="Close Sentinel Demo" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}/><motion.aside className="replay-drawer" role="dialog" aria-modal="true" aria-labelledby="replay-title" initial={{ x: "100%" }} animate={{ x: 0 }} exit={{ x: "100%" }}>
    <div className="drawer-head"><div><span>Controlled simulation</span><h2 id="replay-title">Run a Sentinel Demo</h2></div><button ref={closeRef} type="button" onClick={closeDialog} aria-label="Close replay dialog"><X/></button></div>
    <p className="replay-intro">Synthetic scenarios use the same RiskService and policy path, but never open Razorpay Checkout.</p>
    <div className="scenario-groups"><span>Normal customer behaviour</span><div className="scenario-grid">{Object.entries(scenarioLabels).filter(([id]) => id.startsWith("normal") && scenarios.some((item) => item.id === id)).map(([id, label]) => <button key={id} className={selected === id ? "active" : ""} type="button" onClick={() => setSelected(id)}><FlaskConical size={16}/><span>{label}</span></button>)}</div><span>Suspicious behaviour</span><div className="scenario-grid">{Object.entries(scenarioLabels).filter(([id]) => id.endsWith("attacker") && scenarios.some((item) => item.id === id)).map(([id, label]) => <button key={id} className={selected === id ? "active" : ""} type="button" onClick={() => setSelected(id)}><FlaskConical size={16}/><span>{label}</span></button>)}</div>{system?.model_status === "degraded_rules_only" && <p className="demo-notice">The model is unavailable; this run will use the published fallback rules.</p>}</div>
    <button className="primary-cta full" type="button" onClick={start} disabled={busy}>Start selected scenario <span>→</span></button>
    <div className="replay-progress"><div><span>Attempt</span><strong>{active?.attempt || 0} / {total || "—"}</strong></div><div className="timeline"><i style={{ width: total ? `${((active?.attempt || 0) / total) * 100}%` : "0%" }}/></div></div>
    <div className="replay-result">{active ? <><span className={`activity-decision ${active.operation.decision}`}>{active.operation.decision.toUpperCase()}</span><strong>Sentinel risk {active.operation.risk_score === null ? "—" : Math.round(active.operation.risk_score * 100)}</strong><p>{decisionCopy[active.operation.decision].copy} This controlled simulation never creates a Razorpay order or opens Checkout.</p></> : <p>{message}</p>}</div>
    {steps.length > 0 && <ol className="replay-timeline" aria-label="Scenario attempts">{steps.map((item, index) => <li key={item.id} className={index === cursor ? "active" : ""}><b>{item.attempt}</b><span>{item.operation.decision.toUpperCase()}</span><small>{item.operation.decision === "allow" ? "Order eligible in a real checkout" : item.operation.decision === "review" ? "Prototype holds before order" : "Current attempt stopped"}</small></li>)}</ol>}
    <div className="replay-controls"><button type="button" disabled={busy || cursor <= 0} onClick={() => setCursor(cursor - 1)}><ChevronLeft/>Previous</button><button type="button" disabled={(!playing && busy) || !demoId || complete} onClick={togglePlay}>{playing ? <Pause/> : <Play/>}{playing ? "Pause" : "Play"}</button><button type="button" disabled={busy || !demoId || (complete && cursor >= steps.length - 1)} onClick={next}>Next<StepForward/></button></div>
    <p className="replay-message">{message}</p>
    <button className="reset-demo" type="button" onClick={reset} disabled={busy}><RotateCcw/>Reset demo</button>
  </motion.aside></>}</AnimatePresence>;
}
