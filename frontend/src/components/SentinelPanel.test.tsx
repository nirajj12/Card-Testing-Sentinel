import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SentinelPanel } from "./SentinelPanel";

describe("SentinelPanel", () => {
  it("makes BLOCK suppression visually explicit", () => {
    render(<SentinelPanel phase="decision" progress={4} operation={{ decision: "block", risk_score: .84, risk_band: "very high", reason_codes: ["sustained_request_burst"] }} orderCreated={false} checkoutOpened={false} verified={null} paymentOutcome={null} historyStatus="not_recorded" amount={2499} error=""/>);
    expect(screen.getByText("TEMPORARY BLOCK")).toBeInTheDocument();
    expect(screen.getByText("Razorpay order created").nextElementSibling).toHaveTextContent("NO");
    expect(screen.getByText("Checkout opened").nextElementSibling).toHaveTextContent("NO");
  });

  it("does not present success until a verified backend response exists", () => {
    const { rerender } = render(<SentinelPanel phase="verifying" progress={4} operation={{ decision: "allow", risk_score: .11, reason_codes: [] }} orderCreated checkoutOpened verified={null} paymentOutcome={null} historyStatus="not_recorded" amount={2499} error=""/>);
    expect(screen.queryByText("SIGNATURE VERIFIED")).not.toBeInTheDocument();
    rerender(<SentinelPanel phase="success" progress={4} operation={{ decision: "allow", risk_score: .11, reason_codes: [] }} orderCreated checkoutOpened verified={{ verified: true, sentinel_request_id: "req", razorpay_order_id: "order_test", razorpay_payment_id: "pay_test", payment_status: "signature_verified", outcome_recorded: false, checkout_recorded: false, message: "Awaiting webhook" }} paymentOutcome="signature_verified" historyStatus="awaiting_webhook" amount={2499} error=""/>);
    expect(screen.getByText("Sentinel decision").nextElementSibling).toHaveTextContent("ALLOW");
    expect(screen.getByText("Razorpay outcome").nextElementSibling).toHaveTextContent("SIGNATURE VERIFIED");
    expect(screen.getByText("Verified history").nextElementSibling).toHaveTextContent("AWAITING WEBHOOK");
  });

  it("retains ALLOW separately from a failed Razorpay outcome", () => {
    render(<SentinelPanel phase="failure" progress={4} operation={{ decision: "allow", risk_score: .2, reason_codes: [] }} orderCreated checkoutOpened verified={null} paymentOutcome="failed" historyStatus="recorded_declined" amount={2499} error="Signed failure received"/>);
    expect(screen.getByText("Sentinel decision").nextElementSibling).toHaveTextContent("ALLOW");
    expect(screen.getByText("Razorpay outcome").nextElementSibling).toHaveTextContent("FAILED");
    expect(screen.getByText("Verified history").nextElementSibling).toHaveTextContent("RECORDED DECLINED");
  });
});
