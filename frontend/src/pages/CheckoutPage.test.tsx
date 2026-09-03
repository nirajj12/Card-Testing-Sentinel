import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CartProvider } from "../state/CartContext";
import { api } from "../lib/api";
import { CheckoutPage } from "./CheckoutPage";
import type { RazorpayOptions } from "../types";

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

vi.mock("framer-motion", async (importOriginal) => {
  const actual = await importOriginal<typeof import("framer-motion")>();
  return { ...actual, AnimatePresence: ({ children }: { children: ReactNode }) => children };
});

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
    sessionStorage.clear();
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
    await screen.findAllByText("ALLOW");
    await act(async () => {
      await options!.handler({
        razorpay_order_id: "order",
        razorpay_payment_id: "pay",
        razorpay_signature: "signature",
      });
    });
    await waitFor(() => {
      expect(
        screen.getByText("The payment result could not be verified by the backend."),
      ).toBeVisible();
    });
  });

  it("treats signature verification as awaiting authoritative payment status", async () => {
    allowPrecheck();
    vi.mocked(api.razorpayOrder).mockResolvedValue({ sentinel_request_id:"req",razorpay_order_id:"order",key_id:"key",amount:2499,currency:"INR",test_mode:true,activity_id:"activity" });
    vi.mocked(api.verifyPayment).mockResolvedValue({ verified:true,sentinel_request_id:"req",razorpay_order_id:"order",razorpay_payment_id:"pay",payment_status:"signature_verified",outcome_recorded:false,checkout_recorded:false,message:"Awaiting authoritative payment state" });
    let options: { handler: (payment: { razorpay_order_id:string; razorpay_payment_id:string; razorpay_signature:string }) => Promise<void> } | null = null;
    window.Razorpay = function RazorpayMock(value: typeof options) { options=value; return { open: vi.fn(), on: vi.fn() }; } as never;
    mount(); fireEvent.click(screen.getByRole("button", { name: /Pay securely with Razorpay/i }));
    await waitFor(() => expect(options).not.toBeNull());
    await screen.findAllByText("ALLOW");
    await act(async () => {
      await options!.handler({
        razorpay_order_id: "order",
        razorpay_payment_id: "pay",
        razorpay_signature: "signature",
      });
    });
    await waitFor(() => {
      expect(screen.getByText("Payment signature verified")).toBeVisible();
    });
    expect(screen.getByText(/Waiting for a signed Razorpay server event before showing payment success/i)).toBeVisible();
    expect(screen.queryByText(/Payment successful/i)).not.toBeInTheDocument();
  });

  it("keeps a browser payment failure out of verified behavioral history", async () => {
    allowPrecheck();
    vi.mocked(api.razorpayOrder).mockResolvedValue({ sentinel_request_id:"req",razorpay_order_id:"order",key_id:"key",amount:2499,currency:"INR",test_mode:true,activity_id:"activity" });
    let failureHandler: (() => void) | null = null;
    let dismissHandler: (() => void) | null = null;
    window.Razorpay = function RazorpayMock(options: RazorpayOptions) {
      dismissHandler = options.modal.ondismiss;
      return { open: vi.fn(), on: vi.fn((event: string, handler: () => void) => { if (event === "payment.failed") failureHandler = handler; }) };
    } as never;
    mount(); fireEvent.click(screen.getByRole("button", { name: /Pay securely with Razorpay/i }));
    await waitFor(() => expect(failureHandler).not.toBeNull());
    failureHandler!();
    await waitFor(() => {
      expect(screen.getByText(/waiting for the signed Razorpay server event/i)).toBeVisible();
    });
    expect(screen.getByText("Behavioral history").nextElementSibling).toHaveTextContent("AWAITING SIGNED WEBHOOK");
    expect(screen.queryByText("RECORDED DECLINED")).not.toBeInTheDocument();
    expect(api.verifyPayment).not.toHaveBeenCalled();

    vi.mocked(api.recentActivity).mockResolvedValue({
      items: [{ ...persisted, id: "activity" }],
    });
    await act(async () => dismissHandler!());
    expect(
      await screen.findByText(/Verified decline recorded. A new Pay attempt/i),
    ).toBeVisible();
    expect(screen.getByText("Behavioral history").nextElementSibling).toHaveTextContent("RECORDED DECLINED");
  });

  it("disables Checkout-internal retry and creates a fresh protected attempt on the next Pay click", async () => {
    vi.mocked(api.recentActivity).mockResolvedValue({ items: [] });
    allowPrecheck();
    vi.mocked(api.razorpayOrder).mockImplementation(async (payload) => {
      const request = payload as { sentinel_request_id: string };
      return {
        sentinel_request_id: request.sentinel_request_id,
        razorpay_order_id: `order-${request.sentinel_request_id}`,
        key_id: "key",
        amount: 2499,
        currency: "INR",
        test_mode: true,
        activity_id: `activity-${request.sentinel_request_id}`,
      };
    });

    const checkoutOptions: Array<{
      retry: { enabled: boolean };
      handler: RazorpayOptions["handler"];
    }> = [];
    let failureHandler: (() => void) | null = null;
    window.Razorpay = function RazorpayMock(options: RazorpayOptions) {
      checkoutOptions.push(options);
      return {
        open: vi.fn(),
        on: vi.fn((event: string, handler: () => void) => {
          if (event === "payment.failed") failureHandler = handler;
        }),
      };
    } as never;

    mount();
    fireEvent.click(screen.getByRole("button", { name: /Pay securely with Razorpay/i }));
    await waitFor(() => expect(checkoutOptions).toHaveLength(1));
    expect(checkoutOptions[0].retry).toEqual({ enabled: false });

    await act(async () => failureHandler!());
    expect(api.precheck).toHaveBeenCalledTimes(1);
    expect(api.razorpayOrder).toHaveBeenCalledTimes(1);

    fireEvent.click(await screen.findByRole("button", { name: /Try payment again with Sentinel/i }));
    await waitFor(() => expect(checkoutOptions).toHaveLength(2));
    expect(api.precheck).toHaveBeenCalledTimes(2);
    expect(api.razorpayOrder).toHaveBeenCalledTimes(2);

    const first = vi.mocked(api.precheck).mock.calls[0][0] as Record<string, unknown>;
    const second = vi.mocked(api.precheck).mock.calls[1][0] as Record<string, unknown>;
    expect(second.request_id).not.toBe(first.request_id);
    expect(second.event_id).not.toBe(first.event_id);
    expect(second.device_id).toBe(first.device_id);
    expect(second.session_id).toBe(first.session_id);
    expect(first.event_sequence).toBe(1);
    expect(second.event_sequence).toBe(2);

    await act(async () => failureHandler!());
    fireEvent.click(await screen.findByRole("button", { name: /Try payment again with Sentinel/i }));
    await waitFor(() => expect(checkoutOptions).toHaveLength(3));
    const third = vi.mocked(api.precheck).mock.calls[2][0] as Record<string, unknown>;
    expect(third.request_id).not.toBe(second.request_id);
    expect(third.event_id).not.toBe(second.event_id);
    expect(third.device_id).toBe(first.device_id);
    expect(third.session_id).toBe(first.session_id);
    expect(third.event_sequence).toBe(3);
  });

  it("loads persisted activity again after the page is remounted", async () => {
    const first = mount();
    await waitFor(() => expect(screen.getByText("VERIFIED FAILED PAYMENT")).toBeInTheDocument());
    first.unmount();
    mount();
    await waitFor(() => expect(screen.getByText("VERIFIED FAILED PAYMENT")).toBeInTheDocument());
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
