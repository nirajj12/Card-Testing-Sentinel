import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { HowItWorksPage } from "./HowItWorksPage";

describe("HowItWorksPage", () => {
  it("presents the active model as a risk scorer and Policy v2 as the action layer", () => {
    render(<HowItWorksPage />);

    const flow = screen.getByRole("list", { name: "Sentinel pre-authorization flow" });
    expect(within(flow).getByText("44 causal features")).toBeVisible();
    expect(within(flow).getByText("Model v3.1")).toBeVisible();
    expect(within(flow).getByText("Estimates behavioral risk")).toBeVisible();
    expect(within(flow).getByText("Behavioral risk score")).toBeVisible();
    expect(within(flow).getByText("A score, not an action")).toBeVisible();
    expect(within(flow).getByText("Policy v2")).toBeVisible();
    expect(within(flow).getByText("Chooses the intervention")).toBeVisible();
    expect(screen.getByLabelText("Policy v2 actions")).toHaveTextContent("ALLOWREVIEWBLOCK");
  });

  it("defines the three actions without confusing ALLOW with payment approval or REVIEW with an analyst workflow", () => {
    render(<HowItWorksPage />);

    expect(screen.getByText("ALLOW does not mean payment approved.")).toBeVisible();
    expect(screen.getByText("Elevated risk. The payment path is suppressed.")).toBeVisible();
    expect(screen.getByText(/automated Sentinel state—not human review/i)).toBeVisible();
    expect(screen.getByText(/Supporting behavioral evidence is strong enough to suppress this attempt/i)).toBeVisible();
    expect(document.body.textContent).not.toMatch(/manual review queue|3DS|OTP/i);
  });

  it("makes the current-card and current-outcome causal boundary explicit", () => {
    render(<HowItWorksPage />);

    expect(screen.getByText("What exists when Sentinel decides?")).toBeVisible();
    expect(screen.getByText(/The current card and current payment result cannot affect their own current risk decision/)).toBeVisible();
    expect(screen.getByText(/current card last4 or network, current payment result and current Razorpay outcome/i)).toBeVisible();
  });

  it("explains non-monotonic rescoring without a hardcoded action progression or fake attribution", () => {
    render(<HowItWorksPage />);

    expect(screen.getByText(/A micro-value checkout may already produce elevated model risk/i)).toBeVisible();
    expect(screen.getByText(/risk may rise or fall/i)).toBeVisible();
    expect(screen.getByText(/High risk does not automatically mean BLOCK/i)).toBeVisible();
    expect(document.body).not.toHaveTextContent("ALLOW → REVIEW → BLOCK");
    expect(document.body.textContent).not.toMatch(/SHAP|LIME|contribution|feature importance/i);
  });

  it("contrasts genuine failure and ordinary transaction classification with pre-authorization", () => {
    render(<HowItWorksPage />);

    expect(screen.getByText("Payment failure alone is not card testing.")).toBeVisible();
    expect(screen.getByText(/surrounding behavior remains normal, Sentinel may continue to ALLOW/i)).toBeVisible();
    const comparison = screen.getByLabelText("Traditional fraud classifier compared with Sentinel");
    expect(comparison).toHaveTextContent("Payment exists → features → fraud prediction");
    expect(comparison).toHaveTextContent("Checkout intent → behavioral precheck → policy action → Razorpay order only if Sentinel returns ALLOW");
  });

  it("separates trusted feedback and the three proof layers", () => {
    render(<HowItWorksPage />);

    expect(screen.getByText(/A browser callback is not authoritative/i)).toBeVisible();
    expect(screen.getByText(/A verified signed Razorpay webhook is/i)).toBeVisible();
    expect(screen.getByRole("list", { name: "Trusted payment outcome feedback loop" })).toHaveTextContent("Trusted future history");
    expect(screen.getByRole("heading", { name: "Protected Checkout" })).toBeVisible();
    expect(screen.getByText("Real Razorpay Test Mode integration.")).toBeVisible();
    expect(screen.getByRole("heading", { name: "Replay Lab" })).toBeVisible();
    expect(screen.getByText(/Controlled synthetic behavior through the real scoring runtime/i)).toBeVisible();
    expect(screen.getByText(/Decisions are runtime-generated, not predefined; replay is not Razorpay traffic/i)).toBeVisible();
    expect(screen.getByRole("heading", { name: "Evaluation" })).toBeVisible();
    expect(screen.getByText("Aggregate ML evidence.")).toBeVisible();
  });
});
