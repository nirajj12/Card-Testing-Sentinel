const DEFAULT_TIMEOUT = 10000;

export class ApiError extends Error {
  constructor(message, status = 0, code = "api_error", payload = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.payload = payload;
  }
}

/* Returns { data, status } so callers can display the real HTTP status,
   and throws ApiError carrying the parsed error body for failures. */
export async function call(path, options = {}) {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), options.timeout || DEFAULT_TIMEOUT);
  try {
    const response = await fetch(path, {
      method: options.method || "GET",
      headers: options.body ? { "Content-Type": "application/json" } : {},
      body: options.body ? JSON.stringify(options.body) : undefined,
      signal: controller.signal,
      credentials: "same-origin",
    });
    const contentType = response.headers.get("content-type") || "";
    const payload = contentType.includes("application/json") ? await response.json() : null;
    if (!response.ok) {
      throw new ApiError(
        payload?.message || payload?.detail || "The service could not complete the request.",
        response.status,
        payload?.error || "api_error",
        payload,
      );
    }
    if (payload === null) throw new ApiError("The service returned an invalid response.");
    return { data: payload, status: response.status };
  } catch (error) {
    if (error.name === "AbortError") throw new ApiError("The request timed out.", 0, "timeout");
    if (error instanceof ApiError) throw error;
    throw new ApiError("The local API is unreachable.", 0, "unavailable");
  } finally {
    window.clearTimeout(timer);
  }
}

const get = async (path) => (await call(path)).data;
const post = async (path, body) => (await call(path, { method: "POST", body })).data;

function query(path, values) {
  const params = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    if (value !== "" && value !== null && value !== undefined) params.set(key, value);
  });
  const encoded = params.toString();
  return encoded ? `${path}?${encoded}` : path;
}

export const api = {
  readiness: () => get("/health/ready"),
  system: () => get("/api/system"),
  blindMetrics: () => get("/api/metrics/blind"),
  razorpayStatus: () => get("/api/razorpay/status"),
  razorpayOrder: (body) => post("/api/razorpay/orders", body),
  verifyRazorpayPayment: (body) => post("/api/razorpay/payments/verify", body),
  replayDevices: (filters) => get(query("/api/replay/devices", filters)),
  replayTimeline: (id) => get(`/api/replay/devices/${encodeURIComponent(id)}/timeline`),

  /* Real production endpoints — used by the API console. */
  precheck: (body) => call("/api/precheck", { method: "POST", body }),
  outcome: (body) => call("/api/outcomes", { method: "POST", body }),
  checkout: (body) => call("/api/checkouts", { method: "POST", body }),
  decisions: (limit = 25) => get(query("/api/runtime/decisions", { limit })),
  deviceTimeline: (id) => get(`/api/runtime/devices/${encodeURIComponent(id)}/timeline`),

  /* Mixed merchant traffic. `trafficStart` takes no body on purpose: the
     operator starts traffic, they do not choose who is in it. */
  trafficStart: () => post("/api/demo/traffic/start", {}),
  trafficStep: (trafficRunId) => post("/api/demo/traffic/step", { traffic_run_id: trafficRunId }),
  /* Ground truth is a separate, explicitly-requested call so it never
     travels alongside a decision response. */
  trafficTruth: (trafficRunId) => post("/api/demo/traffic/truth", { traffic_run_id: trafficRunId }),

  demoScenarios: () => get("/api/demo/scenarios"),
  demoStart: (scenario) => post("/api/demo/start", { scenario }),
  demoStep: (demoId) => post("/api/demo/step", { demo_id: demoId }),
};
