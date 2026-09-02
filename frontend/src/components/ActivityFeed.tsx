import { ArrowUpRight } from "lucide-react";
import { useState } from "react";
import { formatPrice } from "../data/products";
import { paymentStatusLabel } from "../features/paymentLifecycle";
import type { ActivityAttempt } from "../types";

type ActivityFilter = "all" | "razorpay_test" | "replay";

type ActivityFeedProps = {
  attempts: ActivityAttempt[];
  onSelect: (attempt: ActivityAttempt) => void;
};

function activityTime(attempt: ActivityAttempt) {
  if (!attempt.timestamp) return `#${attempt.attempt}`;
  return new Date(attempt.timestamp).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function ActivityFeed({ attempts, onSelect }: ActivityFeedProps) {
  const [filter, setFilter] = useState<ActivityFilter>("all");
  const visible =
    filter === "all" ? attempts : attempts.filter((item) => item.source === filter);

  return (
    <section className="activity-panel">
      <div className="activity-head">
        <div>
          <span className="live-label">
            <i />
            Durable activity
          </span>
          <h2>Recent payment activity</h2>
        </div>
        <div className="activity-filters" role="group" aria-label="Activity source">
          <button
            type="button"
            className={filter === "all" ? "active" : ""}
            onClick={() => setFilter("all")}
          >
            All
          </button>
          <button
            type="button"
            className={filter === "razorpay_test" ? "active" : ""}
            onClick={() => setFilter("razorpay_test")}
          >
            Razorpay Test
          </button>
          <button
            type="button"
            className={filter === "replay" ? "active" : ""}
            onClick={() => setFilter("replay")}
          >
            Replay
          </button>
        </div>
      </div>

      <div className="activity-list">
        {visible.length === 0 ? (
          <div className="activity-empty">
            <span>No activity in this view</span>
            <p>Make a Test Mode purchase or run the Sentinel Demo.</p>
          </div>
        ) : (
          visible.slice(0, 12).map((item) => (
            <button type="button" key={item.id} onClick={() => onSelect(item)}>
              <span className="activity-time">{activityTime(item)}</span>
              <strong>{formatPrice(item.amount)}</strong>
              <span className="activity-risk">
                Risk{" "}
                {item.operation.risk_score === null
                  ? "—"
                  : Math.round(item.operation.risk_score * 100)}
              </span>
              <span
                className={`activity-decision ${item.operation.decision}`}
                title="Sentinel decision"
              >
                {item.operation.decision.toUpperCase()}
              </span>
              <span className="activity-outcome" title="Payment lifecycle state">
                {item.source === "replay"
                  ? "NO RAZORPAY"
                  : paymentStatusLabel(item.razorpay_payment_status).toUpperCase()}
              </span>
              <span className={`source-tag ${item.source}`}>
                {item.source === "replay" ? "Replay" : "Razorpay Test"}
              </span>
              <ArrowUpRight size={14} />
            </button>
          ))
        )}
      </div>
    </section>
  );
}
