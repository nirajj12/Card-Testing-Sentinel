import { Check } from "lucide-react";
import type { PaymentPhase } from "./SentinelPanel";

export function LifecycleTracker({ phase, operation, orderCreated, verified }: { phase: PaymentPhase; operation: { decision: string } | null; orderCreated: boolean; verified: unknown }) {
  const decisionDone = Boolean(operation); const stopped = Boolean(operation && operation.decision !== "allow");
  const stages = [
    ["1", "Payment intent", phase !== "idle", phase === "idle" ? "Waiting" : "Received"],
    ["2", "Risk decision", decisionDone, phase === "evaluating" ? "Checking" : decisionDone ? operation!.decision.toUpperCase() : "Pending"],
    ["3", "Razorpay order", orderCreated, stopped ? "Prevented" : orderCreated ? "Created" : "Pending"],
    ["4", "Verification", Boolean(verified), stopped ? "Not reached" : verified ? "Verified" : "Pending"],
  ] as const;
  return <ol className="lifecycle-tracker" aria-label="Payment lifecycle">{stages.map(([number, label, done, state], index) => <li key={label} className={`${done ? "done" : ""} ${stopped && index > 1 ? "stopped" : ""}`}><b>{done ? <Check/> : number}</b><span>{label}<small>{state}</small></span></li>)}</ol>;
}
