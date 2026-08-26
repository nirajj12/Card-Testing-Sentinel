const DEFAULT_TIMEOUT = 10000;

export class ApiError extends Error {
  constructor(message, status = 0, code = "api_error") {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

async function request(path, options = {}) {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), options.timeout || DEFAULT_TIMEOUT);
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
      );
    }
    if (payload === null) throw new ApiError("The service returned an invalid response.");
    return payload;
  } catch (error) {
    if (error.name === "AbortError") throw new ApiError("The request timed out.", 0, "timeout");
    if (error instanceof ApiError) throw error;
    throw new ApiError("The local API is unavailable.", 0, "unavailable");
  } finally {
    window.clearTimeout(timeout);
  }
}

function query(path, values) {
  const params = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    if (value !== "" && value !== null && value !== undefined) params.set(key, value);
  });
  const encoded = params.toString();
  return encoded ? `${path}?${encoded}` : path;
}

export const api = {
  readiness: () => request("/health/ready"),
  system: () => request("/api/v2/system"),
  blindMetrics: () => request("/api/v2/metrics/blind"),
  replayDevices: (filters) => request(query("/api/v2/replay/devices", filters)),
  replayTimeline: (deviceId) => request(`/api/v2/replay/devices/${encodeURIComponent(deviceId)}/timeline`),
  demoScenarios: () => request("/api/v2/demo/scenarios"),
  demoStart: (scenario) => request("/api/v2/demo/start", { method: "POST", body: { scenario } }),
  demoStep: (demoId) => request("/api/v2/demo/step", { method: "POST", body: { demo_id: demoId } }),
  demoReset: () => request("/api/v2/demo/reset", { method: "POST", body: {} }),
};
