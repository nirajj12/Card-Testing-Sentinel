/* Display helpers. Every value is rendered through textContent by the callers. */

export function percent(value, digits = 1) {
  const number = Number(value);
  return Number.isFinite(number) ? `${(number * 100).toFixed(digits)}%` : "—";
}

export function riskScore(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toFixed(3) : "—";
}

export function latency(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  return number < 1 ? `${(number * 1000).toFixed(0)} µs` : `${number.toFixed(2)} ms`;
}

export function integer(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toLocaleString("en-US") : "—";
}

export function currency(value, code = "USD") {
  try {
    return new Intl.NumberFormat(code === "INR" ? "en-IN" : "en-US", {
      style: "currency",
      currency: code,
    }).format(value);
  } catch {
    return `${code} ${value}`;
  }
}

export function timestamp(value) {
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return "—";
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function clockTime(value) {
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return "—";
  return date.toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function titleCase(value) {
  return String(value || "")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function shortId(value, head = 10) {
  const text = String(value ?? "");
  return text.length > head + 6 ? `${text.slice(0, head)}…${text.slice(-4)}` : text;
}

/* Maps an authoritative operations projection onto ONLY the seven approved
   customer-facing states. Nothing about risk score, rule score, reason
   codes, features, thresholds, device/session/IP, scenario or attack
   subtype is read here, let alone shown. A pure function (no DOM access)
   so it can be unit-tested in isolation from the page bootstrap. */
export function customerState(operations) {
  if (!operations) return "Ready to pay.";
  if (operations.decision === "block") return "Payment blocked before authorization.";
  if (operations.decision === "review") return "Payment under review.";
  if (!operations.outcome_status) {
    return "Sent for authorization.";
  }
  return operations.outcome_status === "approved" ? "Payment approved." : "Payment declined by bank.";
}

/* Plain-language explanation for each contracted policy reason code.
   direction: "up" raises risk, "down" lowers it, "ctx" is context only. */
export const REASON_LIBRARY = {
  persistent_high_model_risk: {
    direction: "up",
    title: "Repeated high risk",
    text: "This device scored high on several recent attempts, not just once.",
  },
  consecutive_high_model_risk: {
    direction: "up",
    title: "High risk back to back",
    text: "Consecutive attempts from this device all scored above the threshold.",
  },
  accumulated_model_risk: {
    direction: "up",
    title: "Risk built up over time",
    text: "Risk collected across attempts crossed the limit, even after time decay.",
  },
  high_risk_with_card_switching: {
    direction: "up",
    title: "Card changed after a decline",
    text: "A card was declined and the very next attempt used a different card.",
  },
  cross_session_card_diversity: {
    direction: "up",
    title: "Many cards across sessions",
    text: "Different cards were tried from more than one session on this device.",
  },
  high_risk_with_ip_rotation: {
    direction: "up",
    title: "IP address changed",
    text: "The device moved between IP addresses within the last 24 hours.",
  },
  high_risk_with_card_diversity: {
    direction: "up",
    title: "Several different cards",
    text: "More than one distinct card was used from this device recently.",
  },
  successful_checkout_risk_reduction: {
    direction: "down",
    title: "Genuine purchase completed",
    text: "A real checkout finished earlier, so accumulated risk was reduced.",
  },
  stable_retry_risk_reduction: {
    direction: "down",
    title: "Same card, same amount",
    text: "This looks like an honest retry of one card, so risk was reduced.",
  },
  campaign_threshold_adjustment: {
    direction: "ctx",
    title: "Flash-sale allowance applied",
    text: "A campaign is running, so thresholds and evidence needs were raised.",
  },
  rule_corroborated_review: {
    direction: "up",
    title: "Behaviour rules asked for review",
    text: "Deterministic velocity and diversity rules reached the review level.",
  },
  rule_corroborated_block: {
    direction: "up",
    title: "Behaviour rules asked for block",
    text: "Deterministic velocity and diversity rules reached the block level.",
  },
};

export function explainReason(code) {
  const known = REASON_LIBRARY[code];
  if (known) return known;
  /* This code is not in the published reason-code contract. Failing closed
     here (rather than inventing a plausible-sounding sentence) is
     deliberate: a fabricated explanation for an unrecognized code would be
     an unverifiable claim about why a real decision was made. */
  return {
    direction: "unrecognized",
    title: "Unrecognized reason code — not in the published contract.",
    text: "No explanation is available for this uncontracted code.",
  };
}
