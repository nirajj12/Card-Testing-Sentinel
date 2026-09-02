import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SentinelPanel } from "./SentinelPanel";

describe("SentinelPanel", () => {
  it("makes BLOCK suppression visually explicit", () => {
    render(<SentinelPanel phase="sentinel_decision" progress={4} operation={{ decision: "block", risk_score: .84, risk_band: "very high", reason_codes: ["sustained_request_burst"] }} orderCreated={false} checkoutOpened={false} verified={null} paymentOutcome={null} historyStatus="not_recorded" amount={2499} error=""/>);
    expect(screen.getAllByText("BLOCK").length).toBeGreaterThan(0);
    expect(screen.getByText(/future attempts are independently evaluated/i)).toBeInTheDocument();
    expect(screen.getByText("Razorpay order created").nextElementSibling).toHaveTextContent("NO");
    expect(screen.getByText("Checkout opened").nextElementSibling).toHaveTextContent("NO");
  });

  it("does not present success until a verified backend response exists", () => {
    const { rerender } = render(<SentinelPanel phase="signature_verifying" progress={4} operation={{ decision: "allow", risk_score: .11, reason_codes: [] }} orderCreated checkoutOpened verified={null} paymentOutcome={null} historyStatus="not_recorded" amount={2499} error=""/>);
    expect(screen.queryByText("SIGNATURE VERIFIED")).not.toBeInTheDocument();
    rerender(<SentinelPanel phase="awaiting_authoritative_status" progress={4} operation={{ decision: "allow", risk_score: .11, reason_codes: [] }} orderCreated checkoutOpened verified={{ verified: true, sentinel_request_id: "req", razorpay_order_id: "order_test", razorpay_payment_id: "pay_test", payment_status: "signature_verified", outcome_recorded: false, checkout_recorded: false, message: "Awaiting webhook" }} paymentOutcome="signature_verified" historyStatus="awaiting_signed_webhook" amount={2499} error=""/>);
    expect(screen.getByText("Sentinel decision").nextElementSibling).toHaveTextContent("ALLOW");
    expect(screen.getByText("Payment lifecycle state").nextElementSibling).toHaveTextContent("SIGNATURE VERIFIED — AWAITING PAYMENT STATUS");
    expect(screen.getByText("Behavioral history").nextElementSibling).toHaveTextContent("AWAITING SIGNED WEBHOOK");
    expect(screen.getByText(/Waiting for a signed Razorpay server event before showing payment success/i)).toBeInTheDocument();
    expect(screen.queryByText(/Payment successful/i)).not.toBeInTheDocument();
  });

  it("shows completion only for an authoritative captured payment", () => {
    render(<SentinelPanel phase="payment_complete" progress={4} operation={{ decision: "allow", risk_score: .11, reason_codes: [] }} orderCreated checkoutOpened verified={{ verified: true, sentinel_request_id: "req", razorpay_order_id: "order_test", razorpay_payment_id: "pay_test", payment_status: "captured", outcome_recorded: true, checkout_recorded: true, message: "Captured" }} paymentOutcome="captured" historyStatus="recorded_approved" amount={2499} error=""/>);
    expect(screen.getByText("Authoritative payment complete")).toBeInTheDocument();
    expect(screen.getByText("Payment lifecycle state").nextElementSibling).toHaveTextContent("CAPTURED");
    expect(screen.getByText("Behavioral history").nextElementSibling).toHaveTextContent("RECORDED APPROVED");
  });

  it("retains ALLOW separately from a failed Razorpay outcome", () => {
    render(<SentinelPanel phase="failure" progress={4} operation={{ decision: "allow", risk_score: .2, reason_codes: [] }} orderCreated checkoutOpened verified={null} paymentOutcome="failed" historyStatus="recorded_declined" amount={2499} error="Signed failure received"/>);
    expect(screen.getByText("Sentinel decision").nextElementSibling).toHaveTextContent("ALLOW");
    expect(screen.getByText("Payment lifecycle state").nextElementSibling).toHaveTextContent("VERIFIED FAILED PAYMENT");
    expect(screen.getByText("Behavioral history").nextElementSibling).toHaveTextContent("RECORDED DECLINED");
  });

  it("keeps REVIEW before order creation and checkout", () => {
    render(<SentinelPanel phase="sentinel_decision" progress={4} operation={{ decision: "review", risk_score: .55, reason_codes: [] }} orderCreated={false} checkoutOpened={false} verified={null} paymentOutcome={null} historyStatus="not_recorded" amount={2499} error=""/>);
    expect(screen.getByText("Razorpay order created").nextElementSibling).toHaveTextContent("NO");
    expect(screen.getByText("Checkout opened").nextElementSibling).toHaveTextContent("NO");
    expect(screen.getByText("Prevented")).toBeInTheDocument();
    expect(screen.getByText(/does not operate a manual-review or step-up flow/i)).toBeInTheDocument();
  });
});
