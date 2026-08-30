/* Display helpers. Every value is rendered through textContent by the callers. */

export function percent(value, digits = 1) {
  const number = Number(value);
  return Number.isFinite(number) ? `${(number * 100).toFixed(digits)}%` : "—";
}

export function riskScore(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  /* A calibrated score that rounds to 0.000 or 1.000 is not literally zero or
     one, and printing it that way makes a probabilistic model look like a
     step function. Show the bound instead of a false exact value. */
  /* A tiny non-zero score rounding to 0.000 is a display artifact worth
     correcting. A score of exactly 1.0 is not: isotonic calibration maps its
     top bin to 1.0, and printing ">0.999" would invent precision the
     calibrator does not have. */
  if (number > 0 && number < 0.0005) return "<0.001";
  return number.toFixed(3);
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


/* Operator-facing description for each Replay Lab scenario.

   Deliberately kept on the frontend: SCENARIO_CATALOG is pinned by
   test_scenario_catalog_contains_no_expected_decision_or_score_hint to
   exactly {label, attempts}, and these strings describe *behaviour a
   shopper or attacker exhibits*, never an expected decision. Nothing here
   is sent to the backend. */
export const SCENARIO_LIBRARY = {
  normal_customer: "One temporary processor hiccup, then success. Same card, same session throughout.",
  normal_bad_luck: "A genuine shopper hitting real declines, who switches to a second card once.",
  flash_standard: "Campaign checkout retrying through gateway load on one card.",
  flash_hard_retry: "Aggressive legitimate retries during a sale, falling back to a backup card at the end.",
  burst_attacker: "Seconds-scale attempts, a new card almost every time, one session.",
  evasive_attacker: "Card, session and IP rotated in small groups, with irregular pauses in between.",
  patient_attacker: "A new session per attempt, spread across hours and days rather than seconds.",
};

export function scenarioDescription(id) {
  return SCENARIO_LIBRARY[id] || "Synthetic behaviour plan.";
}

/* Virtual-clock helpers. The simulator runs on a compressed virtual clock,
   so these format an *offset from the run start*, never wall-clock now.
   Rendering Date.now() while claiming a multi-hour span would be a lie
   about what the data represents. */
export function virtualElapsed(seconds) {
  const total = Number(seconds);
  if (!Number.isFinite(total) || total < 0) return "—";
  const days = Math.floor(total / 86400);
  const hours = Math.floor((total % 86400) / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const remainder = Math.floor(total % 60);
  if (days) return `D${days + 1} ${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}`;
  if (hours) return `${hours}h ${String(minutes).padStart(2, "0")}m`;
  return `${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`;
}

/* Which virtual day an offset falls on, used to group the long-horizon
   Patient Card Testing replay honestly instead of flattening days into a
   single list of timestamps. */
export function virtualDay(seconds) {
  const total = Number(seconds);
  if (!Number.isFinite(total)) return 1;
  return Math.floor(total / 86400) + 1;
}

/* The lifecycle of one attempt as the operations projection currently
   knows it. A traffic row starts with no processor outcome -- that event
   genuinely has not happened yet on the virtual clock -- and is patched
   later. Saying "awaiting" is accurate; inventing a result is not. */
export function lifecycleSummary(operations) {
  if (!operations) return "—";
  if (operations.decision === "block") return "Suppressed before authorization";
  if (operations.checkout_status === "completed") return "Approved · checkout completed";
  if (operations.outcome_status === "approved") return "Approved by bank";
  if (operations.outcome_status === "declined") return "Declined by bank";
  return "Sent · awaiting processor outcome";
}


/* True when the calibrator has saturated rather than expressed certainty. */
export function isSaturated(value) {
  return Number(value) >= 1;
}
