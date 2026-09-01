import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../lib/api";
import type { BlindMetrics } from "../types";
import { EvidencePage } from "./EvidencePage";

const fixture: BlindMetrics = {
  status: "available", source: "published.json", label: "evaluation", blind_version: "blind", active_runtime_version: "current", model_version: "model", policy_version: "policy", verdict: "NO_GO", consumed: true,
  active_device_counts: { attack: 40, legitimate: 60 }, headline: { attack_intervention_rate: .7123, attack_block_rate: .521, legitimate_intervention_rate: .234, legitimate_block_rate: .102 },
  model_metrics: { pr_auc: .654321, roc_auc: .765432, brier: .2, ece: .1 }, policy_metrics: { attack_review_or_higher_rate: .7123, attack_block_rate: .521, legitimate_review_or_higher_rate: .234, legitimate_block_rate: .102 },
  operating_targets: { detect_attack: "PASS", protect_legitimate: "FAIL" }, detection_by_attempt: { "1": .2, "3": .7 }, scenario_metrics: [],
  limitations: { hardest_attacks: ["patient_attacker"], highest_friction: ["normal_bad_luck"], summary: "Meaningful friction remains." }, historical_evidence: { version: "older", source: "old.json", comparable_to_blind_v2: false }, replay: { status: "not_packaged", reason: "Replay not packaged.", missing_artifact: "x" }, disclosure: "Synthetic evidence only."
};

describe("EvidencePage", () => {
  afterEach(() => vi.restoreAllMocks());
  it("renders exact API-backed metrics, disclaimer, and collapsed technical details", async () => {
    vi.spyOn(api, "blindMetrics").mockResolvedValue(fixture);
    render(<EvidencePage/>);
    await waitFor(() => expect(screen.getAllByText("71.23%").length).toBeGreaterThan(0));
    expect(screen.getByText("Synthetic evidence only.")).toBeInTheDocument();
    const summary = screen.getByText("Technical details");
    expect(summary.closest("details")).not.toHaveAttribute("open");
    expect(screen.getByText("0.654321")).toBeInTheDocument();
  });
});
