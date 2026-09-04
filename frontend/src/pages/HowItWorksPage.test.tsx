import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { HowItWorksPage } from "./HowItWorksPage";

function renderPage() {
  return render(<MemoryRouter><HowItWorksPage /></MemoryRouter>);
}

describe("HowItWorksPage", () => {
  it("shows the real pre-authorization sequence and makes policy the decision layer", () => {
    renderPage();
    expect(screen.getByRole("heading", { name: /how sentinel decidesbefore order creation/i })).toBeVisible();
    expect(screen.getByRole("button", { name: /Current Checkout ContextWhat the merchant can see now/i })).toBeVisible();
    expect(screen.getByRole("button", { name: /Trusted Prior HistoryVerified earlier outcomes only/i })).toBeVisible();
    expect(screen.getByRole("button", { name: /44 Causal FeaturesSafe facts available before payment/i })).toBeVisible();
    expect(screen.getByRole("button", { name: /Model v3.1Estimates card-testing risk/i })).toBeVisible();
    expect(screen.getByRole("button", { name: /Decision layerPolicy v2 ActionChooses what happens next/i })).toBeVisible();
  });

  it("defaults to ALLOW and lets users inspect all policy routes", () => {
    renderPage();
    const allow = screen.getByRole("button", { name: "Allow" });
    const review = screen.getByRole("button", { name: "Review" });
    const block = screen.getByRole("button", { name: "Block" });
    expect(allow).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: /Create Razorpay Test Mode Order/i }));
    expect(screen.getByText(/does not mean Razorpay has approved the payment/i)).toBeVisible();
    fireEvent.click(review);
    expect(review).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText(/no human-review queue/i)).toBeVisible();
    fireEvent.click(block);
    expect(block).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText(/No Razorpay order is created/i)).toBeVisible();
    expect(screen.getAllByRole("button", { name: /Suppress Order Creation/i })).toHaveLength(1);
  });

  it("keeps the causal boundary and trusted feedback explicit", () => {
    renderPage();
    expect(screen.getByRole("heading", { name: "Sentinel cannot use information from the future." })).toBeVisible();
    expect(screen.getByText("Current card number, CVV, or expiry")).toBeVisible();
    expect(screen.getByText(/current payment result cannot influence its own risk decision/i)).toBeVisible();
    expect(screen.getByRole("list", { name: "Trusted payment outcome feedback loop" })).toHaveTextContent("Signed Webhook");
    expect(screen.getByRole("list", { name: "Trusted payment outcome feedback loop" })).toHaveTextContent("Verify + Deduplicate");
    expect(screen.getByText(/Browser callbacks are not trusted evidence/i)).toBeVisible();
  });

  it("ends with one CTA to the protected checkout", () => {
    renderPage();
    expect(screen.getByRole("link", { name: /Try Protected Checkout/i })).toHaveAttribute("href", "/checkout");
    expect(screen.getAllByRole("link", { name: /Try Protected Checkout/i })).toHaveLength(1);
  });
});
