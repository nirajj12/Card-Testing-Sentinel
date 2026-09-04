import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { Navbar } from "../components/Navbar";
import { LandingPage } from "./LandingPage";

vi.mock("../lib/api", () => ({ api: { system: vi.fn().mockResolvedValue({ ready: true, model_status: "ready" }) } }));

describe("public navigation and home", () => {
  it("uses Results and routes the primary calls to action", () => {
    render(<MemoryRouter><Navbar/><LandingPage/></MemoryRouter>);
    expect(screen.getByRole("link", { name: "Results" })).toHaveAttribute("href", "/results");
    expect(screen.getByRole("link", { name: "Try the Demo" })).toHaveAttribute("href", "/checkout");
    expect(screen.getAllByRole("link", { name: "Try protected checkout" })).toEqual(expect.arrayContaining([expect.objectContaining({ className: "primary-cta" })]));
    expect(screen.getAllByRole("link", { name: "Try protected checkout" })[0]).toHaveAttribute("href", "/checkout");
    expect(screen.getAllByRole("link", { name: "Run attack simulation" })[0]).toHaveAttribute("href", "/checkout?demo=burst_attacker");
    expect(screen.getByText(/Razorpay Test Mode/)).toBeVisible();
    expect(screen.getByText("Illustrative sequence — Replay decisions are runtime-scored and may rise or fall.")).toBeVisible();
  });

  it("exposes mobile navigation state and closes with Escape", () => {
    render(<MemoryRouter><Navbar/></MemoryRouter>); const menu=screen.getByRole("button",{name:"Open navigation"}); expect(menu).toHaveAttribute("aria-expanded","false"); fireEvent.click(menu); expect(screen.getByRole("button",{name:"Close navigation"})).toHaveAttribute("aria-expanded","true"); fireEvent.keyDown(document,{key:"Escape"}); expect(screen.getByRole("button",{name:"Open navigation"})).toHaveAttribute("aria-expanded","false");
  });

  it("reduces motion without hiding page content", () => {
    vi.stubGlobal("matchMedia", vi.fn().mockReturnValue({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() }));
    render(<MemoryRouter><LandingPage/></MemoryRouter>);
    expect(screen.getByRole("heading", { name: /Stop card testing/ })).toBeVisible();
    expect(screen.getByText(/44 merchant-visible behavioural signals/)).toBeVisible();
    expect(screen.queryByText(/39 behavioural signals/i)).not.toBeInTheDocument();
  });

  it("contrasts an ordinary checkout with a card-testing burst", () => {
    render(<MemoryRouter><LandingPage/></MemoryRouter>);
    expect(screen.getByText("Order path open")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Testing burst" }));
    expect(screen.getByText("Stopped before Razorpay")).toBeVisible();
    expect(screen.getByText("Changing cards")).toBeVisible();
  });

  it("explains each boundary outcome and clearly links to How It Works", () => {
    render(<MemoryRouter><LandingPage/></MemoryRouter>);
    expect(screen.getByRole("link", { name: /See the complete How It Works page/i })).toHaveAttribute("href", "/how-it-works");
    expect(screen.getByText("A normal purchase continues")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: /REVIEW.*Uncertain pattern/i }));
    expect(screen.getByText("An uncertain pattern is held")).toBeVisible();
    expect(screen.getByText(/This prototype creates no Razorpay order/)).toBeVisible();
  });
});
