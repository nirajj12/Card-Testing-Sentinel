import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../lib/api";
import type { Operation } from "../types";
import { ReplayDrawer } from "./ReplayDrawer";

const scenarios = [
  { id: "normal_customer", label: "Everyday Checkout", attempts: 2 },
  { id: "normal_bad_luck", label: "Bad-Luck Retry", attempts: 4 },
  { id: "flash_standard", label: "Flash Sale", attempts: 3 },
  { id: "flash_hard_retry", label: "Flash-Sale Hard Retry", attempts: 5 },
  { id: "burst_attacker", label: "Burst Card Testing", attempts: 10 },
  { id: "evasive_attacker", label: "Evasive Card Testing", attempts: 9 },
  { id: "patient_attacker", label: "Patient Card Testing", attempts: 9 },
];

const zeroEvidence = {
  requests_5m: 0,
  recent_failures_24h: 0,
  decline_streak: 0,
  sessions_24h: 0,
  ip_changes_24h: 0,
  successful_checkouts_30d: 0,
};

function operation(overrides: Partial<Operation>): Operation {
  return {
    decision: "allow",
    risk_score: .013,
    reason_codes: [],
    evidence: zeroEvidence,
    authorization: "sent",
    outcome_status: "declined",
    checkout_status: null,
    protected_reference: "protected-ref",
    ...overrides,
  };
}

function step(attempt: number, operations: Operation, complete = false) {
  return {
    complete,
    attempt: {
      attempt,
      amount: attempt === 1 ? 2 : 3,
      currency: "INR",
      campaign_active: false,
      timestamp: `2026-09-04T00:00:0${attempt}Z`,
      elapsed_seconds: attempt === 1 ? 0 : attempt * 4,
    },
    operations,
    timeline: [],
  };
}

function mockCatalog() {
  vi.spyOn(api, "demoScenarios").mockResolvedValue({ items: scenarios });
  vi.spyOn(api, "demoStart").mockResolvedValue({ demo_id: "demo-1", total_attempts: 3 });
  vi.spyOn(api, "demoReset").mockResolvedValue({ reset: true });
}

async function startAndNext() {
  fireEvent.click(await screen.findByRole("button", { name: /Start selected scenario/ }));
  await waitFor(() => expect(screen.getByRole("button", { name: /Next/ })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: /Next/ }));
}

describe("ReplayDrawer", () => {
  afterEach(() => vi.restoreAllMocks());

  it("renders all backend-supported scenarios with behavioral descriptions and authentic replay copy", async () => {
    mockCatalog();
    render(<ReplayDrawer open onClose={vi.fn()} onAttempt={vi.fn()} system={{ ready: true, model_status: "ready" }}/>);

    for (const name of ["Everyday Checkout", "Genuine Retry", "Flash Sale", "Flash-Sale Hard Retry", "Burst Card Testing", "Evasive Card Testing", "Patient Card Testing"]) {
      expect(await screen.findByRole("button", { name: new RegExp(name) })).toBeVisible();
    }
    expect(screen.getByText(/ALLOW \/ REVIEW \/ BLOCK is not predefined/)).toBeVisible();
    expect(screen.getByText(/simulated lifecycle events, not Razorpay traffic/i)).toBeVisible();
    expect(screen.getByText(/several payment declines can remain ALLOW/i)).toBeVisible();
    expect(document.body.textContent).not.toMatch(/SHAP|contribution percentage|Razorpay webhook/i);
  });

  it("collapses the catalog after start, shows scenario-aware comparison, and restores it on reset", async () => {
    mockCatalog();
    vi.spyOn(api, "demoStart").mockResolvedValue({ demo_id: "flash-demo", total_attempts: 5 });
    render(<ReplayDrawer open onClose={vi.fn()} onAttempt={vi.fn()} system={{ ready: true, model_status: "ready" }}/>);

    fireEvent.click(await screen.findByRole("button", { name: /Flash-Sale Hard Retry/ }));
    expect(screen.getByText(/Compare with Burst Card Testing/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: /Start selected scenario/ }));

    const summary = await screen.findByRole("region", { name: "Active scenario" });
    expect(summary).toHaveTextContent("Flash-Sale Hard Retry");
    expect(summary).toHaveTextContent("LEGITIMATE");
    expect(summary).toHaveTextContent("5 attempts");
    expect(screen.queryByRole("button", { name: /Everyday Checkout/ })).not.toBeInTheDocument();
    expect(screen.getByText(/similar repeated checkout pressure can produce very different risk and policy behavior/)).toBeVisible();

    fireEvent.click(within(summary).getByRole("button", { name: /Reset demo/ }));
    expect(await screen.findByRole("button", { name: /Everyday Checkout/ })).toBeVisible();
    expect(screen.getByRole("button", { name: /Burst Card Testing/ })).toBeVisible();
  });

  it("keeps the completed Burst footer aligned with the selected attempt", async () => {
    mockCatalog();
    vi.spyOn(api, "demoStart").mockResolvedValue({ demo_id: "burst-demo", total_attempts: 10 });
    const decisions: Operation["decision"][] = ["allow", "allow", "review", "allow", "review", "allow", "block", "allow", "allow", "review"];
    let stepCall = 0;
    vi.spyOn(api, "demoStep").mockImplementation(async () => {
      const attempt = ++stepCall;
      return step(attempt, operation({ decision: decisions[attempt - 1], risk_score: attempt / 10 }), attempt === 10);
    });
    render(<ReplayDrawer open onClose={vi.fn()} onAttempt={vi.fn()} system={{ ready: true, model_status: "ready" }}/>);

    fireEvent.click(await screen.findByRole("button", { name: /Burst Card Testing/ }));
    expect(screen.getByText(/five fast legitimate retries remained ALLOW/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: /Start selected scenario/ }));
    for (let attempt = 1; attempt <= 10; attempt += 1) {
      await waitFor(() => expect(screen.getByRole("button", { name: /Next/ })).toBeEnabled());
      fireEvent.click(screen.getByRole("button", { name: /Next/ }));
      await screen.findByRole("button", { name: new RegExp(`Inspect attempt ${attempt},`) });
    }

    fireEvent.click(screen.getByRole("button", { name: /Inspect attempt 7, block/ }));
    expect(within(screen.getByLabelText("Selected attempt decision")).getByText("BLOCK")).toBeVisible();
    expect(screen.getByText("Burst Card Testing · selected attempt 7 · BLOCK")).toBeVisible();
    expect(screen.queryByText(/backend returned REVIEW/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Inspect attempt 10, review/ }));
    expect(within(screen.getByLabelText("Selected attempt decision")).getByText("REVIEW")).toBeVisible();
    expect(screen.getByText("Burst Card Testing · selected attempt 10 · REVIEW")).toBeVisible();
  });

  it("shows precise model risk, no first delta, first-attempt REVIEW truth, policy evidence and suppression", async () => {
    mockCatalog();
    vi.spyOn(api, "demoStep").mockResolvedValue(step(1, operation({
      decision: "review",
      risk_score: .926,
      reason_codes: ["elevated_model_risk", "block_withheld_insufficient_evidence"],
      authorization: "suppressed",
      outcome_status: null,
      checkout_status: null,
    })));
    render(<ReplayDrawer open onClose={vi.fn()} onAttempt={vi.fn()} system={{ ready: true, model_status: "ready" }}/>);
    await startAndNext();

    expect((await screen.findAllByText("92.6 / 100")).length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("No previous attempt")).toBeVisible();
    expect(screen.getByText("Initial suspicious signal")).toBeVisible();
    expect(screen.getByText(/Micro-value checkout behavior at ₹2 raised the model risk/)).toBeVisible();
    expect(screen.getByText(/stronger corroborating history was not yet available/)).toBeVisible();
    expect(screen.getByText("Elevated behavioral risk")).toBeVisible();
    expect(screen.getByText("Automatic block withheld")).toBeVisible();
    expect(screen.queryByText("Repeated verified failures")).not.toBeInTheDocument();
    expect(screen.getByText(/Policy did not have enough corroborating evidence for automatic BLOCK/)).toBeVisible();
    expect(screen.getByText("SUPPRESSED")).toBeVisible();
    expect(screen.getAllByText("NOT CREATED")).toHaveLength(2);
  });

  it("renders positive and negative runtime deltas, compares changed evidence, and selects exact attempts", async () => {
    mockCatalog();
    const calls = [
      step(1, operation({ risk_score: .50 })),
      step(2, operation({ risk_score: .684, evidence: { ...zeroEvidence, requests_5m: 1, sessions_24h: 1 } })),
      step(3, operation({ risk_score: .421, evidence: { ...zeroEvidence, requests_5m: 2, sessions_24h: 1 } }), true),
    ];
    vi.spyOn(api, "demoStep").mockImplementation(async () => calls.shift());
    render(<ReplayDrawer open onClose={vi.fn()} onAttempt={vi.fn()} system={{ ready: true, model_status: "ready" }}/>);

    await startAndNext();
    await waitFor(() => expect(screen.getAllByText("50.0 / 100").length).toBeGreaterThanOrEqual(2));
    fireEvent.click(screen.getByRole("button", { name: /Next/ }));
    expect((await screen.findAllByText("↑ +18.4")).length).toBeGreaterThanOrEqual(2);
    const changes = screen.getByText("What changed?").parentElement as HTMLElement;
    expect(within(changes).getByText("Observed requests in 5 minutes")).toBeVisible();
    expect(within(changes).getByText("Observed sessions in 24 hours")).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: /Next/ }));
    expect((await screen.findAllByText("↓ -26.3")).length).toBeGreaterThanOrEqual(2);
    fireEvent.click(screen.getByRole("button", { name: /Inspect attempt 1/ }));
    expect(screen.getByText("No previous attempt")).toBeVisible();
    expect(screen.getAllByText("50.0 / 100").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByRole("button", { name: /Inspect attempt 1/ })).toHaveAttribute("aria-pressed", "true");
  });

  it("handles unchanged evidence without implying model contribution", async () => {
    mockCatalog();
    vi.spyOn(api, "demoStep")
      .mockResolvedValueOnce(step(1, operation({ risk_score: .30 })))
      .mockResolvedValueOnce(step(2, operation({ risk_score: .30 })));
    render(<ReplayDrawer open onClose={vi.fn()} onAttempt={vi.fn()} system={{ ready: true, model_status: "ready" }}/>);
    await startAndNext();
    await waitFor(() => expect(screen.getAllByText("30.0 / 100").length).toBeGreaterThanOrEqual(2));
    fireEvent.click(screen.getByRole("button", { name: /Next/ }));

    expect((await screen.findAllByText("→ 0.0")).length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("No major tracked evidence changed since the previous attempt.")).toBeVisible();
    expect(screen.getByText("Observed changes are context, not model attribution.")).toBeVisible();
  });

  it("separates ALLOW from a later simulated outcome and renders BLOCK suppression", async () => {
    mockCatalog();
    vi.spyOn(api, "demoStep")
      .mockResolvedValueOnce(step(1, operation({ decision: "allow", risk_score: .13, authorization: "sent", outcome_status: "declined" })))
      .mockResolvedValueOnce(step(2, operation({ decision: "block", risk_score: .97, reason_codes: ["elevated_model_risk", "verified_decline_streak"], authorization: "suppressed", outcome_status: null, checkout_status: null })));
    render(<ReplayDrawer open onClose={vi.fn()} onAttempt={vi.fn()} system={{ ready: true, model_status: "ready" }}/>);
    await startAndNext();

    expect(await screen.findByText(/Payment approval is determined later by the simulated outcome/)).toBeVisible();
    expect(screen.getByText("SENT")).toBeVisible();
    expect(screen.getByText("DECLINED")).toBeVisible();
    expect(screen.getByText("NOT COMPLETED")).toBeVisible();
    expect(screen.queryByText(/payment approved/i)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Next/ }));
    expect(await screen.findByText(/Corroborating behavioral evidence was strong enough/)).toBeVisible();
    expect(screen.getByText("SUPPRESSED")).toBeVisible();
    expect(screen.getAllByText("NOT CREATED")).toHaveLength(2);
  });

  it("resets through the backend and preserves modal focus restoration", async () => {
    mockCatalog();
    vi.spyOn(api, "demoStep").mockResolvedValue(step(1, operation({})));
    function Harness() { const [open, setOpen] = useState(false); return <><button type="button" onClick={() => setOpen(true)}>Launch replay</button><ReplayDrawer open={open} onClose={() => setOpen(false)} onAttempt={vi.fn()} system={{ ready: true, model_status: "ready" }}/></>; }
    render(<Harness/>);
    const trigger = screen.getByRole("button", { name: "Launch replay" });
    trigger.focus(); fireEvent.click(trigger);
    expect(await screen.findByRole("dialog", { name: "Replay Lab" })).toHaveAttribute("aria-modal", "true");
    await waitFor(() => expect(screen.getByRole("button", { name: "Close replay dialog" })).toHaveFocus());
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(trigger).toHaveFocus();
  });

  it("traps keyboard focus inside Replay and keeps the backdrop out of the tab order", async () => {
    mockCatalog();
    function Harness() { return <><button type="button">Background action</button><ReplayDrawer open onClose={vi.fn()} onAttempt={vi.fn()} system={{ ready: true, model_status: "ready" }}/></>; }
    const { container } = render(<Harness/>);
    const background = screen.getByText("Background action");
    const close = await screen.findByRole("button", { name: "Close replay dialog" });
    await waitFor(() => expect(close).toHaveFocus());
    const reset = screen.getByRole("button", { name: /Reset demo/ });

    fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
    expect(reset).toHaveFocus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(close).toHaveFocus();

    background.focus();
    expect(close).toHaveFocus();
    expect(background).toHaveAttribute("inert");
    expect(background).toHaveAttribute("aria-hidden", "true");
    expect(container.querySelector(".drawer-backdrop")).toHaveAttribute("tabindex", "-1");
    expect(container.querySelector(".drawer-backdrop")).toHaveAttribute("aria-hidden", "true");
  });
});
