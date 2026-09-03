import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { HowItWorksPage } from "./HowItWorksPage";

describe("HowItWorksPage", () => {
  it("defaults to the normal story and renders only that story", () => {
    render(<HowItWorksPage/>);
    expect(screen.getByRole("tab", { name: "Normal purchase" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("One familiar purchase, one clean path.")).toBeInTheDocument();
    expect(screen.queryByText("Small attempts become a visible sequence.")).not.toBeInTheDocument();
  });

  it("switches branches by click and keyboard", () => {
    render(<HowItWorksPage/>);
    fireEvent.click(screen.getByRole("tab", { name: "Card-testing burst" }));
    expect(screen.getByText("Small attempts become a visible sequence.")).toBeInTheDocument();
    fireEvent.keyDown(screen.getByRole("tab", { name: "Card-testing burst" }), { key: "ArrowRight" });
    expect(screen.getByRole("tab", { name: "Difficult genuine retry" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("Genuine failure can resemble abuse.")).toBeInTheDocument();
  });

  it("uses the active signal count and keeps decision semantics bounded", () => {
    render(<HowItWorksPage/>);
    expect(screen.getByText("Sentinel constructs 44 ordered behavioral signals")).toBeVisible();
    expect(screen.getByText("ALLOW permits Razorpay order creation")).toBeVisible();
    expect(screen.getByText(/payment authorization has not happened yet/i)).toBeVisible();
  });
});
