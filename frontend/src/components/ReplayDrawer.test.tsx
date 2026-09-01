import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../lib/api";
import { ReplayDrawer } from "./ReplayDrawer";
import { useState } from "react";

describe("ReplayDrawer", () => {
  afterEach(() => vi.restoreAllMocks());
  it("renders backend replay progression and resets through the API", async () => {
    vi.spyOn(api, "demoScenarios").mockResolvedValue({ items: [{ id: "normal_customer" }, { id: "burst_attacker" }] });
    vi.spyOn(api, "demoStart").mockResolvedValue({ demo_id: "demo-1", total_attempts: 2 });
    vi.spyOn(api, "demoStep").mockResolvedValue({ complete: false, attempt: { attempt: 1, amount: 2400, currency: "INR" }, operations: { decision: "allow", risk_score: .03, reason_codes: [] } });
    const reset = vi.spyOn(api, "demoReset").mockResolvedValue({ reset: true });
    render(<ReplayDrawer open onClose={vi.fn()} onAttempt={vi.fn()} system={{ ready: true, model_status: "ready" }}/>);
    fireEvent.click(await screen.findByRole("button", { name: "Normal Purchase" }));
    fireEvent.click(screen.getByRole("button", { name: /Start selected scenario/ }));
    await waitFor(() => expect(screen.getByRole("button", { name: /Next/ })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: /Next/ }));
    expect(await screen.findByText("Order path eligible")).toBeInTheDocument();
    expect(api.demoStep).toHaveBeenCalledWith("demo-1");
    fireEvent.click(screen.getByRole("button", { name: "Reset demo" }));
    await waitFor(() => expect(reset).toHaveBeenCalled());
    await waitFor(() => expect(screen.getAllByText(/Demo reset/).length).toBeGreaterThan(0));
  });

  it("behaves as a modal dialog and returns focus after Escape", async () => {
    vi.spyOn(api, "demoScenarios").mockResolvedValue({ items: [] });
    function Harness(){const [open,setOpen]=useState(false);return <><button type="button" onClick={()=>setOpen(true)}>Launch replay</button><ReplayDrawer open={open} onClose={()=>setOpen(false)} onAttempt={vi.fn()} system={{ready:true,model_status:"ready"}}/></>}
    render(<Harness/>); const trigger=screen.getByRole("button",{name:"Launch replay"}); trigger.focus(); fireEvent.click(trigger);
    const dialog=await screen.findByRole("dialog",{name:"Run a Sentinel Demo"}); expect(dialog).toHaveAttribute("aria-modal","true");
    await waitFor(()=>expect(screen.getByRole("button",{name:"Close replay dialog"})).toHaveFocus());
    fireEvent.keyDown(document,{key:"Escape"}); await waitFor(()=>expect(screen.queryByRole("dialog")).not.toBeInTheDocument()); expect(trigger).toHaveFocus();
  });
});
