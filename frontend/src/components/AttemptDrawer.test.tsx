import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import type { ActivityAttempt } from "../types";
import { AttemptDrawer } from "./AttemptDrawer";

const attempt: ActivityAttempt = {
  id: "attempt-1",
  attempt: 1,
  amount: 2499,
  currency: "INR",
  source: "razorpay_test",
  operation: {
    decision: "allow",
    risk_score: 0.1,
    reason_codes: [],
  },
};

function DrawerHarness() {
  const [selected, setSelected] = useState<ActivityAttempt | null>(null);
  return (
    <>
      <button type="button" onClick={() => setSelected(attempt)}>
        Open attempt
      </button>
      <AttemptDrawer attempt={selected} onClose={() => setSelected(null)} />
    </>
  );
}

describe("AttemptDrawer accessibility", () => {
  it("exposes a modal title, closes with Escape, and restores focus", async () => {
    render(<DrawerHarness />);
    const opener = screen.getByRole("button", { name: "Open attempt" });

    opener.focus();
    fireEvent.click(opener);

    const dialog = screen.getByRole("dialog", { name: "Attempt details" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    await waitFor(() =>
      expect(screen.getAllByRole("button", { name: "Close attempt details" })[1]).toHaveFocus(),
    );

    fireEvent.keyDown(document, { key: "Escape" });

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await waitFor(() => expect(opener).toHaveFocus());
  });
});
