export class ApiError extends Error {
  status: number;
  code: string;
  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new ApiError(response.status, payload.error || "request_failed", payload.message || "The request could not be completed.");
  }
  return payload as T;
}

export const api = {
  system: <T>() => request<T>("/api/system"),
  precheck: <T>(body: unknown) => request<T>("/api/precheck", { method: "POST", body: JSON.stringify(body) }),
  razorpayOrder: <T>(body: unknown) => request<T>("/api/razorpay/orders", { method: "POST", body: JSON.stringify(body) }),
  verifyPayment: <T>(body: unknown) => request<T>("/api/razorpay/payments/verify", { method: "POST", body: JSON.stringify(body) }),
  checkoutOpened: <T>(body: unknown) => request<T>("/api/razorpay/orders/checkout-opened", { method: "POST", body: JSON.stringify(body) }),
  recentActivity: <T>() => request<T>("/api/activity/recent"),
  demoScenarios: <T>() => request<T>("/api/demo/scenarios"),
  demoStart: <T>(scenario: string) => request<T>("/api/demo/start", { method: "POST", body: JSON.stringify({ scenario }) }),
  demoStep: <T>(demoId: string) => request<T>("/api/demo/step", { method: "POST", body: JSON.stringify({ demo_id: demoId }) }),
  blindMetrics: <T>() => request<T>("/api/metrics/blind"),
};

export const friendlyError = (error: unknown) => error instanceof ApiError ? error.message : "The operation could not be completed safely.";
