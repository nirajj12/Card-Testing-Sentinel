"""Server-side allowlisted projection of decision evidence.

This is backend preparation for the future fraud-operations panel (not
built yet). Every value returned here is taken verbatim from the exact
response/snapshot produced for a real decision -- nothing is recomputed,
and nothing outside the fixed allowlists below is ever included. In
particular this module never sees, and could not leak, the full 44-feature
vector, raw identifiers, the HMAC secret, scenario labels, or private
policy thresholds.
"""

from __future__ import annotations

#: Fixed, generic risk bands. Deliberately independent of the frozen
#: policy's actual (private) review/block thresholds -- these are display
#: buckets, not a restatement of policy.
_RISK_BANDS = (
    (0.25, "low"),
    (0.50, "elevated"),
    (0.75, "high"),
)

#: The only causal snapshot fields ever allowed to leave the backend for
#: operations display. Matches the Stage 4 allowlist exactly: recent
#: attempt count, recent distinct-card count, prior decline streak, session
#: count, IP-change count, prior successful checkout count.
SAFE_EVIDENCE_FEATURES: tuple[str, ...] = (
    "prior_attempts_24h",
    "distinct_cards_24h",
    "prior_decline_streak",
    "sessions_24h",
    "ip_changes_24h",
    "prior_successful_checkouts",
)


def risk_band(risk_score: float) -> str:
    """Bucket a risk score into a fixed, coarse, non-confidential band."""
    for threshold, label in _RISK_BANDS:
        if risk_score < threshold:
            return label
    return "very_high"


def safe_evidence(snapshot: dict | None) -> dict:
    """Select only the allowlisted causal signals from a decision snapshot.

    Returns whatever subset of the allowlist is present in ``snapshot``. An
    idempotent replay has no fresh snapshot at all (the stored response is
    returned as-is, deliberately without rescoring) -- in that case this
    returns an empty dict rather than recomputing anything, matching "a
    small allowlist of safe causal signals when available".
    """
    if not snapshot:
        return {}
    return {name: snapshot[name] for name in SAFE_EVIDENCE_FEATURES if name in snapshot}


def build_projection(
    *,
    decision: str,
    risk_score: float,
    rule_score: int,
    reason_codes: list[str],
    state_version: int,
    latency_ms: float,
    idempotent_replay: bool,
    authorization: str,
    outcome_status: str | None,
    checkout_status: str | None,
    evidence: dict,
    protected_reference: str | None,
) -> dict:
    """Assemble the allowlisted operations projection for one attempt.

    Every argument here must already be a safe, decision-time value pulled
    from the real API response or the real decision snapshot -- this
    function only selects and labels, it does not compute or infer
    anything new.
    """
    if authorization not in ("sent", "suppressed"):
        raise ValueError("authorization must be 'sent' or 'suppressed'")
    return {
        "decision": decision,
        "risk_score": risk_score,
        "risk_band": risk_band(risk_score),
        "risk_score_label": "risk score — not a guaranteed fraud probability",
        "rule_score": rule_score,
        "reason_codes": list(reason_codes),
        "state_version": state_version,
        "latency_ms": latency_ms,
        "idempotent_replay": idempotent_replay,
        "authorization": authorization,
        "outcome_status": outcome_status,
        "checkout_status": checkout_status,
        "evidence": evidence,
        "protected_reference": protected_reference,
    }
