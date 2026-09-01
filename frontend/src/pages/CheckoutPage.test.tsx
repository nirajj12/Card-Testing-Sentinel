import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CartProvider } from "../state/CartContext";
import { api } from "../lib/api";
import { CheckoutPage } from "./CheckoutPage";

vi.mock("../lib/api", () => ({
  api: {
    system: vi.fn(),
    recentActivity: vi.fn(),
    precheck: vi.fn(),
    razorpayOrder: vi.fn(),
    verifyPayment: vi.fn(),
    checkoutOpened: vi.fn(),
  },
  friendlyError: () => "Safe error",
}));

const persisted = {
  id: "protected-activity",
  protected_reference: "protected-activity",
  timestamp: "2030-01-01T00:00:00Z",
  amount: 2499,
  currency: "INR",
  source: "razorpay_test" as const,
  sentinel_decision: "allow" as const,
  risk_score: 0.1,
  reason_codes: [],
  evidence: {},
  razorpay_order_created: true,
  checkout_opened: true,
  razorpay_payment_status: "failed",
  signature_verified: false,
  webhook_verified: true,
  history_status: "recorded_declined",
  payment_attempt_count: 1,
};

function mount() {
  return render(<MemoryRouter><CartProvider><CheckoutPage/></CartProvider></MemoryRouter>);
}

describe("CheckoutPage activity hydration", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.querySelectorAll("script[data-razorpay-checkout]").forEach((node) => node.remove());
    delete window.Razorpay;
    vi.mocked(api.system).mockResolvedValue({ ready: true, model_status: "ready" });
    vi.mocked(api.recentActivity).mockResolvedValue({ items: [persisted] });
    vi.mocked(api.checkoutOpened).mockResolvedValue({});
  });

  function allowPrecheck() {
    vi.mocked(api.precheck).mockResolvedValue({ decision: "allow", risk_score: .1, reason_codes: [], evidence: {}, protected_reference: "ref" } as never);
  }

  it("keeps ALLOW visible while showing an order-creation failure", async () => {
    allowPrecheck(); vi.mocked(api.razorpayOrder).mockRejectedValue(new Error("order failed")); mount();
    fireEvent.click(screen.getByRole("button", { name: /Pay securely with Razorpay/i }));
    expect(await screen.findByText("Sentinel allowed this attempt, but the Razorpay order could not be created.")).toBeInTheDocument();
    expect(screen.getAllByText("ALLOW").length).toBeGreaterThan(0);
  });

  it("shows a Checkout-loading failure after a successful order", async () => {
    allowPrecheck(); vi.mocked(api.razorpayOrder).mockResolvedValue({ sentinel_request_id:"req",razorpay_order_id:"order",key_id:"key",amount:2499,currency:"INR",test_mode:true,activity_id:"activity" }); mount();
    fireEvent.click(screen.getByRole("button", { name: /Pay securely with Razorpay/i }));
    await waitFor(() => expect(document.querySelector("script[data-razorpay-checkout]")).not.toBeNull());
    const script = document.querySelector<HTMLScriptElement>("script[data-razorpay-checkout]")!;
    fireEvent.error(script);
    expect(await screen.findByText("Sentinel allowed this attempt, but Razorpay Checkout could not open.")).toBeInTheDocument();
    expect(screen.getByText("Razorpay order created").nextElementSibling).toHaveTextContent("YES");
  });

  it("shows a backend-verification failure separately", async () => {
    allowPrecheck(); vi.mocked(api.razorpayOrder).mockResolvedValue({ sentinel_request_id:"req",razorpay_order_id:"order",key_id:"key",amount:2499,currency:"INR",test_mode:true,activity_id:"activity" }); vi.mocked(api.verifyPayment).mockRejectedValue(new Error("verify failed"));
    let options: { handler: (payment: { razorpay_order_id:string; razorpay_payment_id:string; razorpay_signature:string }) => Promise<void> } | null = null;
    window.Razorpay = function RazorpayMock(value: typeof options) { options=value; return { open: vi.fn(), on: vi.fn() }; } as never;
    mount(); fireEvent.click(screen.getByRole("button", { name: /Pay securely with Razorpay/i }));
    await waitFor(() => expect(options).not.toBeNull());
    await options!.handler({ razorpay_order_id:"order",razorpay_payment_id:"pay",razorpay_signature:"signature" });
    expect(await screen.findByText("The payment result could not be verified by the backend.")).toBeVisible();
  });

  it("loads persisted activity again after the page is remounted", async () => {
    const first = mount();
    await waitFor(() => expect(screen.getByText("FAILED")).toBeInTheDocument());
    first.unmount();
    mount();
    await waitFor(() => expect(screen.getByText("FAILED")).toBeInTheDocument());
    expect(api.recentActivity).toHaveBeenCalledTimes(2);
  });

  it("starts the precheck when randomUUID is unavailable on a local origin", async () => {
    let randomSeed = 6;
    vi.stubGlobal("crypto", {
      getRandomValues: (values: Uint8Array) => {
        randomSeed += 1;
        values.fill(randomSeed);
        return values;
      },
    });
    vi.mocked(api.precheck).mockResolvedValue({
      decision: "block",
      risk_score: 0.9,
      reason_codes: ["velocity_high"],
      evidence: {},
      protected_reference: "test-reference",
    });

    mount();
    fireEvent.click(screen.getByRole("button", { name: /Pay securely with Razorpay/i }));

    await waitFor(() => expect(api.precheck).toHaveBeenCalledTimes(1));
    expect(api.precheck).toHaveBeenCalledWith(expect.objectContaining({
      request_id: expect.stringMatching(/^store-request-[0-9a-f]{18}$/),
      event_id: expect.stringMatching(/^store-precheck-[0-9a-f]{18}$/),
    }));

    const firstRequest = vi.mocked(api.precheck).mock.calls[0][0] as { customer_id: string; device_id: string };
    fireEvent.click(await screen.findByRole("button", { name: "Start fresh Test Mode shopper" }));
    expect(screen.getByText("Waiting for payment attempt")).toBeInTheDocument();
    expect((screen.getByLabelText("Email address") as HTMLInputElement).value).toMatch(/^builder\+[0-9a-f]{10}@example\.com$/);

    fireEvent.click(screen.getByRole("button", { name: /Pay securely with Razorpay/i }));
    await waitFor(() => expect(api.precheck).toHaveBeenCalledTimes(2));
    const secondRequest = vi.mocked(api.precheck).mock.calls[1][0] as { customer_id: string; device_id: string };
    expect(secondRequest.customer_id).not.toBe(firstRequest.customer_id);
    expect(secondRequest.device_id).not.toBe(firstRequest.device_id);
    vi.unstubAllGlobals();
  });
});
