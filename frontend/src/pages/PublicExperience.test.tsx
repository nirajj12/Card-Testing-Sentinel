import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { Navbar } from "../components/Navbar";
import { LandingPage } from "./LandingPage";

vi.mock("../lib/api", () => ({ api: { system: vi.fn().mockResolvedValue({ ready: true, model_status: "ready" }) } }));

describe("public navigation and home", () => {
  it("uses Results and routes the primary calls to action", () => {
    render(<MemoryRouter><Navbar/><LandingPage/></MemoryRouter>);
    expect(screen.getByRole("link", { name: "Results" })).toHaveAttribute("href", "/results");
    expect(screen.getAllByRole("link", { name: "Try the Demo" })).toEqual(expect.arrayContaining([expect.objectContaining({ className: "primary-cta" })]));
    expect(screen.getAllByRole("link", { name: "Try the Demo" })[1]).toHaveAttribute("href", "/checkout");
    expect(screen.getByRole("link", { name: "See how it works" })).toHaveAttribute("href", "/how-it-works");
    expect(screen.getByText(/Prototype in Razorpay Test Mode/)).toBeVisible();
  });

  it("reduces motion without hiding page content", () => {
    vi.stubGlobal("matchMedia", vi.fn().mockReturnValue({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() }));
    render(<MemoryRouter><LandingPage/></MemoryRouter>);
    expect(screen.getByRole("heading", { name: /Stop card testing/ })).toBeVisible();
    expect(screen.getByText("39 signal categories")).toBeVisible();
  });
});
