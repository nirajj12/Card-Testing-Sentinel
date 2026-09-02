import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ActivityFeed } from "./ActivityFeed";
import type { ActivityAttempt } from "../types";

const attempts: ActivityAttempt[] = [
  { id: "real", attempt: 1, amount: 2499, currency: "INR", source: "razorpay_test", operation: { decision: "allow", risk_score: .1, reason_codes: [] }, razorpay_payment_status: "failed" },
  { id: "replay", attempt: 2, amount: 2, currency: "INR", source: "replay", operation: { decision: "block", risk_score: .9, reason_codes: [] } },
];

describe("ActivityFeed", () => {
  it("keeps Razorpay Test and Replay sources explicit and filterable", () => {
    render(<ActivityFeed attempts={attempts} onSelect={vi.fn()}/>);
    expect(screen.getAllByText("Razorpay Test")).toHaveLength(2);
    expect(screen.getAllByText("Replay")).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "Razorpay Test" }));
    expect(screen.getByText("VERIFIED FAILED PAYMENT")).toBeInTheDocument();
    expect(screen.queryByText("NO RAZORPAY")).not.toBeInTheDocument();
  });
});
