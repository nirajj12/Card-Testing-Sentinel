import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { publicEvidence } from "../data/publicEvidence";
import { EvidencePage } from "./EvidencePage";

describe("EvidencePage", () => {
  it("shows the exact public headline metrics and defines REVIEW+", () => {
    render(<EvidencePage />);
    expect(screen.getByText("96.4%", { selector: ".results-metric-grid strong" })).toBeVisible();
    expect(screen.getByText("60.8%", { selector: ".results-metric-grid strong" })).toBeVisible();
    expect(screen.getByText("20.72%", { selector: ".results-metric-grid strong" })).toBeVisible();
    expect(screen.getByText("0.16%", { selector: ".results-metric-grid strong" })).toBeVisible();
    expect(screen.getByText("What REVIEW+ means")).toBeVisible();
    expect(screen.getByText(/REVIEW\+ is the intervention class: REVIEW or BLOCK/)).toBeVisible();
  });

  it("renders attack, delay, and genuine-friction values without inventing attempt 4", () => {
    render(<EvidencePage />);
    expect(screen.getByRole("img", { name: /Stealth low-amount attack.*100%/ })).toBeVisible();
    expect(screen.getByRole("img", { name: /Hybrid credential probe.*60.8%/ })).toBeVisible();
    expect(screen.getByRole("img", { name: /Mixed-card probe.*44.93%/ })).toBeVisible();
    expect(screen.getByRole("img", { name: /Attempt 3: 92.16% surfaced/ })).toBeVisible();
    expect(screen.queryByText("Attempt 4")).not.toBeInTheDocument();
    expect(screen.getByRole("img", { name: /Charity spike.*0%/ })).toBeVisible();
    expect(screen.getByRole("img", { name: /B2B corporate-card traffic.*7.2%/ })).toBeVisible();
    expect(screen.getByRole("img", { name: /Ordinary checkout.*25.3%/ })).toBeVisible();
  });

  it("presents strengths and limitations without contradicting the stealth result", () => {
    render(<EvidencePage />);
    const improvement = screen.getByText("What needs improvement").closest("article");
    expect(improvement).toHaveTextContent("20.72% overall legitimate REVIEW+ friction");
    expect(improvement).toHaveTextContent("Ordinary checkout reached 25.3% intervention");
    expect(improvement).not.toHaveTextContent("Stealth low-amount attack");
    expect(screen.getByText("Current limitation")).toBeVisible();
  });

  it("uses accurate public runtime, Razorpay, webhook, and economic language", () => {
    render(<EvidencePage />);
    expect(screen.getByText("Local non-production latency; not production Razorpay latency.")).toBeVisible();
    expect(screen.getByText("Razorpay Test Mode verified")).toBeVisible();
    expect(screen.getByText("ALLOW created a test order")).toBeVisible();
    expect(screen.getByText("Signed webhook handling verified locally.")).toBeVisible();
    expect(screen.getByText(/not measured Razorpay economics, observed savings/)).toBeVisible();
  });

  it("makes evaluation scope explicit without exposing implementation artifacts", () => {
    const { container } = render(<EvidencePage />);
    const visible = container.textContent || "";
    const scope = screen.getByLabelText("Evaluation evidence scope");
    expect(scope).toHaveTextContent("Frozen PBRSS-v1 shifted stress");
    expect(scope).toHaveTextContent("Development validation reported separately");
    expect(scope).toHaveTextContent("Conclusion: MIXED");
    expect(scope).toHaveTextContent("production_ready=false");
    expect(visible).not.toMatch(/Model v(?:1|2|3)|Blind v/);
    expect(visible).not.toMatch(/artifact(?:s)?\//i);
    expect(visible).not.toMatch(/\bSHA\b|freeze commit|post_blind|post_stress/i);
  });

  it("keeps centralized public values aligned with the frozen figure manifest", () => {
    const manifestPath = resolve(
      process.cwd(),
      "artifacts/figures/figure_manifest.json",
    );
    const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
    const attack = manifest.figures.find(
      (figure: { filename: string }) =>
        figure.filename === "pbrss_scenario_performance.png",
    );
    const latency = manifest.figures.find(
      (figure: { filename: string }) => figure.filename === "phase_4c_latency.png",
    );
    const economics = manifest.figures.find(
      (figure: { filename: string }) =>
        figure.filename === "phase_4d_economic_scenarios.png",
    );

    const attackByScenario = Object.fromEntries(
      attack.metrics_used.map(
        (row: { scenario: string; review_plus_pct: number }) =>
          [row.scenario, row.review_plus_pct],
      ),
    );
    expect(publicEvidence.attackScenarios.map((row) => row.reviewPlusPct)).toEqual([
      attackByScenario.stealth_low_amount_drip,
      attackByScenario.hybrid_credential_stuffing_probe,
      attackByScenario.mixed_card_probe,
    ]);
    expect(publicEvidence.runtime.p50Ms).toBeCloseTo(latency.metrics_used.p50);
    expect(publicEvidence.runtime.p95Ms).toBeCloseTo(latency.metrics_used.p95);
    expect(publicEvidence.economics.map((row) => row.netValueInr)).toEqual([
      economics.metrics_used.quiet_day,
      economics.metrics_used.active_attack_campaign,
      economics.metrics_used.high_value_merchant,
    ]);
  });
});
