import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { HowItWorksPage } from "./HowItWorksPage";

describe("HowItWorksPage", () => {
  it("defaults to ALLOW and renders only the selected branch", () => {
    render(<HowItWorksPage/>);
    expect(screen.getByRole("tab", { name: "ALLOW" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("Continue to Razorpay")).toBeInTheDocument();
    expect(screen.queryByText("Pause for merchant intervention")).not.toBeInTheDocument();
  });

  it("switches branches by click and keyboard", () => {
    render(<HowItWorksPage/>);
    fireEvent.click(screen.getByRole("tab", { name: "REVIEW" }));
    expect(screen.getByText("Pause for merchant intervention")).toBeInTheDocument();
    fireEvent.keyDown(screen.getByRole("tab", { name: "REVIEW" }), { key: "ArrowRight" });
    expect(screen.getByRole("tab", { name: "TEMPORARY BLOCK" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("Temporarily stop the payment path")).toBeInTheDocument();
  });
});
