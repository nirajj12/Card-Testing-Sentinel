import { Check } from "lucide-react";
import { isAuthoritativePayment } from "../features/paymentLifecycle";
import type { PaymentPhase, VerifiedPayment } from "../types";

type LifecycleTrackerProps = {
  phase: PaymentPhase;
  operation: { decision: string } | null;
  orderCreated: boolean;
  checkoutOpened: boolean;
  verified: VerifiedPayment | null;
  paymentOutcome: string | null;
  historyStatus: string;
};

type LifecycleStage = readonly [number: string, label: string, done: boolean, state: string];

export function LifecycleTracker({
  phase,
  operation,
  orderCreated,
  checkoutOpened,
  verified,
  paymentOutcome,
  historyStatus,
}: LifecycleTrackerProps) {
  const decisionDone = Boolean(operation);
  const stopped = Boolean(operation && operation.decision !== "allow");
  const authoritative = isAuthoritativePayment(paymentOutcome, historyStatus);

  const stages: LifecycleStage[] = [
    ["1", "Payment intent", phase !== "idle", phase === "idle" ? "Waiting" : "Received"],
    [
      "2",
      "Sentinel risk decision",
      decisionDone,
      phase === "sentinel_evaluating"
        ? "Checking"
        : decisionDone
          ? operation!.decision.toUpperCase()
          : "Pending",
    ],
    ["3", "Razorpay order", orderCreated, stopped ? "Prevented" : orderCreated ? "Created" : "Pending"],
    ["4", "Checkout", checkoutOpened, stopped ? "Not reached" : checkoutOpened ? "Opened" : "Pending"],
    [
      "5",
      "Signature",
      Boolean(verified),
      stopped
        ? "Not reached"
        : verified
          ? "Verified"
          : phase === "signature_verifying"
            ? "Verifying"
            : "Pending",
    ],
    [
      "6",
      "Payment status",
      authoritative,
      stopped
        ? "Not reached"
        : authoritative
          ? "Authoritative"
          : paymentOutcome === "failed_unverified"
            ? "Unverified report"
            : verified
              ? "Awaiting server event"
              : "Pending",
    ],
  ];

  return (
    <ol className="lifecycle-tracker" aria-label="Payment lifecycle">
      {stages.map(([number, label, done, state], index) => (
        <li
          key={label}
          className={`${done ? "done" : ""} ${stopped && index > 1 ? "stopped" : ""}`}
        >
          <b>{done ? <Check /> : number}</b>
          <span>
            {label}
            <small>{state}</small>
          </span>
        </li>
      ))}
    </ol>
  );
}
