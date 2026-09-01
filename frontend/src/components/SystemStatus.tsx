import { Activity, BrainCircuit, CreditCard, Database, X } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { SystemStatus as Status } from "../types";

export function SystemStatus() {
  const [status, setStatus] = useState<Status | null>(null);
  const [open, setOpen] = useState(false);
  useEffect(() => { api.system<Status>().then(setStatus).catch(() => setStatus({ ready: false, model_status: "unavailable" })); }, []);
  const healthy = Boolean(status?.ready);
  return <div className="system-status">
    <button className={`health-pill ${healthy ? "ready" : "error"}`} type="button" onClick={() => setOpen(!open)} aria-expanded={open} title="Running with the current 39-signal risk model"><i />{status ? (healthy ? "Demo system online" : "Demo unavailable") : "Connecting"}</button>
    {open && <div className="system-popover">
      <div className="system-popover-head"><div><span>Runtime status</span><strong>{healthy ? "All core services ready" : "Attention required"}</strong></div><button type="button" onClick={() => setOpen(false)}><X size={15}/></button></div>
      <p className="status-summary">Running with the current 39-signal risk model.</p>
      <StatusRow icon={BrainCircuit} label="Decision service" value={status?.model_status === "ready" ? "Ready" : "Rules-only / unavailable"}/>
      <StatusRow icon={Activity} label="Operational policy" value={status?.policy_stage ? "Ready" : healthy ? "Ready" : "Unavailable"}/>
      <StatusRow icon={Database} label="Event store" value={status?.database?.integrity === "ok" || status?.database?.type === "memory" ? "Healthy" : status ? "Check required" : "Checking"}/>
      <StatusRow icon={CreditCard} label="Razorpay" value={status?.razorpay?.configured ? "Test Mode ready" : "Not configured"}/>
    </div>}
  </div>;
}

function StatusRow({ icon: Icon, label, value }: { icon: typeof Activity; label: string; value: string }) {
  return <div className="system-row"><Icon size={16}/><span>{label}</span><strong>{value}</strong></div>;
}
