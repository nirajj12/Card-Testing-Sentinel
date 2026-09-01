"""Validation-only operating-point selection for Policy v2.

Replays the frozen Model v2 validation scores through candidate policies and
reports device-level friction and detection for each. The model is never
refitted and validation is the only split touched -- no blind data exists for
v2, and Blind v1.1 is consumed and out of scope.

Selection is constraint-first: a candidate is eligible only if it stays
inside the false-friction budget declared in `configs/policy_v2.yaml` BEFORE
any candidate is scored. Among eligible candidates the ranking objective is
documented and applied in a fixed order. Maximising recall alone is exactly
the failure mode this design exists to avoid.

The search is vectorised because the v2 decision is row-local: a block needs
a score, an evidence count and a trust flag, none of which depend on earlier
decisions. `assert_engine_parity` re-runs the selected candidate through the
real `RiskPolicyV2` and fails if the two ever disagree, so the fast path can
never quietly diverge from the engine that would serve production.
"""

from __future__ import annotations

from itertools import product

import numpy as np
import pandas as pd

from card_testing_sentinel.policy.engine_v2 import RiskPolicyV2
from card_testing_sentinel.policy.evidence_v2 import (
    EVIDENCE_SETS,
    TRUST_LEVELS,
    evidence_codes_v2,
    trust_codes,
)

ACTIONS = ("allow", "review", "block")
_ORDER = {"allow": 0, "review": 1, "block": 2}


def precompute(frame: pd.DataFrame, features: tuple[str, ...]) -> dict:
    """Evidence counts and trust flags per row, for every candidate design.

    Computed once. The evidence definitions themselves come from the policy
    module, not from a reimplementation here.
    """
    snapshots = frame.loc[:, list(features)].to_dict("records")
    evidence = {
        name: np.array(
            [len(evidence_codes_v2(row, name)) for row in snapshots], dtype=int
        )
        for name in EVIDENCE_SETS
    }
    trust = {
        level: np.array(
            [bool(trust_codes(row, level)) for row in snapshots], dtype=bool
        )
        for level in TRUST_LEVELS
    }
    return {"evidence": evidence, "trust": trust, "snapshots": snapshots}


def decide_vector(
    risk: np.ndarray,
    campaign: np.ndarray,
    evidence_count: np.ndarray,
    trusted: np.ndarray,
    config: dict,
) -> np.ndarray:
    """The v2 decision as an array of action ranks (0 allow, 1 review, 2 block)."""
    review_at = float(config["review_threshold"]) + np.where(
        campaign, float(config.get("campaign_review_increment", 0.0)), 0.0
    )
    block_at = float(config["block_threshold"]) + np.where(
        campaign, float(config.get("campaign_block_increment", 0.0)), 0.0
    )
    block_allowed = (evidence_count >= int(config["block_evidence"])) & ~trusted
    blocked = (risk >= block_at) & block_allowed
    reviewed = (~blocked) & (risk >= review_at)
    return np.where(blocked, 2, np.where(reviewed, 1, 0))


def device_view(frame: pd.DataFrame, ranks: np.ndarray) -> pd.DataFrame:
    """One row per device: did it ever get reviewed / blocked, and when."""
    working = frame[
        ["device_id", "label", "scenario", "population", "merchant_kind"]
    ].copy()
    working["customer_present"] = frame.customer_id_present.eq(1.0).to_numpy()
    working["timestamp"] = pd.to_datetime(frame.timestamp, format="ISO8601")
    working["rank"] = ranks
    working = working.sort_values(["device_id", "timestamp"], kind="mergesort")
    working["attempt"] = working.groupby("device_id").cumcount() + 1

    first_review = working.loc[working["rank"] >= 1].groupby("device_id").attempt.min()
    first_block = working.loc[working["rank"] >= 2].groupby("device_id").attempt.min()
    view = working.groupby("device_id").agg(
        label=("label", "first"),
        scenario=("scenario", "first"),
        population=("population", "first"),
        merchant_kind=("merchant_kind", "first"),
        customer_present=("customer_present", "any"),
        attempts=("attempt", "max"),
        max_action=("rank", "max"),
    )
    view["ever_reviewed"] = view.max_action >= 1
    view["ever_blocked"] = view.max_action >= 2
    view["first_review_attempt"] = first_review
    view["first_block_attempt"] = first_block
    return view


def _rate(series: pd.Series) -> float:
    return round(float(series.mean()), 4) if len(series) else 0.0


def _quantile(series: pd.Series, q: float) -> float | None:
    clean = series.dropna()
    return float(clean.quantile(q)) if len(clean) else None


def summarise(devices: pd.DataFrame) -> dict:
    attack = devices.loc[devices.label.eq(1)]
    legitimate = devices.loc[devices.label.eq(0)]
    return {
        "attack_devices": int(len(attack)),
        "legitimate_devices": int(len(legitimate)),
        "attack_review_or_higher_recall": _rate(attack.ever_reviewed),
        "attack_block_recall": _rate(attack.ever_blocked),
        "attack_never_detected": int((~attack.ever_reviewed).sum()),
        "legitimate_review_or_higher_rate": _rate(legitimate.ever_reviewed),
        "legitimate_block_rate": _rate(legitimate.ever_blocked),
        "legitimate_reviewed_devices": int(legitimate.ever_reviewed.sum()),
        "legitimate_blocked_devices": int(legitimate.ever_blocked.sum()),
        "median_first_review_attempt": _quantile(attack.first_review_attempt, 0.5),
        "p90_first_review_attempt": _quantile(attack.first_review_attempt, 0.9),
        "median_first_block_attempt": _quantile(attack.first_block_attempt, 0.5),
        "p90_first_block_attempt": _quantile(attack.first_block_attempt, 0.9),
        "cumulative_attack_detection": {
            str(attempt): {
                "review_or_higher_rate": _rate(
                    attack.first_review_attempt.le(attempt).fillna(False)
                ),
                "block_rate": _rate(
                    attack.first_block_attempt.le(attempt).fillna(False)
                ),
            }
            for attempt in (1, 2, 3, 5)
        },
    }


def scenario_view(devices: pd.DataFrame) -> pd.DataFrame:
    grouped = devices.groupby("scenario").agg(
        population=("population", "first"),
        label=("label", "first"),
        devices=("label", "size"),
        reviewed_devices=("ever_reviewed", "sum"),
        blocked_devices=("ever_blocked", "sum"),
        median_first_review=("first_review_attempt", "median"),
        median_first_block=("first_block_attempt", "median"),
    )
    grouped["review_or_higher_rate"] = (
        grouped.reviewed_devices / grouped.devices
    ).round(4)
    grouped["block_rate"] = (grouped.blocked_devices / grouped.devices).round(4)
    grouped["measure"] = np.where(
        grouped.label.eq(1), "attack_recall", "legitimate_false_positive_rate"
    )
    return grouped.drop(columns="label").sort_values(
        ["population", "block_rate"], ascending=[True, False]
    )


def merchant_view(devices: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for kind, group in devices.groupby("merchant_kind"):
        attack = group.loc[group.label.eq(1)]
        legitimate = group.loc[group.label.eq(0)]
        rows.append(
            {
                "merchant_kind": kind,
                "devices": int(len(group)),
                "legitimate_devices": int(len(legitimate)),
                "attack_devices": int(len(attack)),
                "legitimate_review_or_higher_rate": _rate(legitimate.ever_reviewed),
                "legitimate_block_rate": _rate(legitimate.ever_blocked),
                "attack_review_or_higher_recall": _rate(attack.ever_reviewed),
                "attack_block_recall": _rate(attack.ever_blocked),
            }
        )
    return pd.DataFrame(rows).sort_values("legitimate_block_rate", ascending=False)


def segment_view(devices: pd.DataFrame) -> pd.DataFrame:
    """Policy outcomes split by whether the account was identified.

    Guest traffic must not absorb disproportionate blocking.
    """
    rows = []
    for present, group in devices.groupby("customer_present"):
        attack = group.loc[group.label.eq(1)]
        legitimate = group.loc[group.label.eq(0)]
        rows.append(
            {
                "segment": "customer_present" if present else "customer_absent",
                "devices": int(len(group)),
                "attack_devices": int(len(attack)),
                "legitimate_devices": int(len(legitimate)),
                "attack_review_or_higher_recall": _rate(attack.ever_reviewed),
                "attack_block_recall": _rate(attack.ever_blocked),
                "legitimate_review_or_higher_rate": _rate(legitimate.ever_reviewed),
                "legitimate_block_rate": _rate(legitimate.ever_blocked),
                "legitimate_blocked_devices": int(legitimate.ever_blocked.sum()),
            }
        )
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# candidate grid
# --------------------------------------------------------------------------


def candidate_configs_v2(search: dict, base: dict) -> list[dict]:
    """The compact, predefined grid. Block must not sit below review."""
    candidates: list[dict] = []
    for review, block, evidence, evidence_set, trust, (
        campaign_r,
        campaign_b,
    ) in product(
        [round(float(v), 3) for v in search["review_thresholds"]],
        [round(float(v), 3) for v in search["block_thresholds"]],
        [int(v) for v in search["block_evidence_counts"]],
        list(search["evidence_sets"]),
        list(search["trust_suppression"]),
        [tuple(pair) for pair in search["campaign_increments"]],
    ):
        if block < review:
            continue
        candidates.append(
            {
                **base,
                "family": "evidence_gated_v2",
                "review_threshold": review,
                "block_threshold": block,
                "block_evidence": evidence,
                "evidence_set": evidence_set,
                "trust_suppression": trust,
                "campaign_review_increment": float(campaign_r),
                "campaign_block_increment": float(campaign_b),
            }
        )
    return candidates


def candidate_label(config: dict) -> str:
    return (
        f"r{config['review_threshold']}_b{config['block_threshold']}"
        f"_e{config['block_evidence']}_{config['evidence_set']}"
        f"_trust-{config['trust_suppression']}"
        f"_camp{config['campaign_review_increment']}"
    )


# --------------------------------------------------------------------------
# constraints, ranking, selection
# --------------------------------------------------------------------------


def scenario_rate_caps(devices: float, constraints: dict) -> tuple[float, float]:
    """Uniform stress-cohort guardrails with a minimum count granularity.

    Dataset v3's legitimate scenarios are deliberately enriched stress
    cohorts, not random samples from the aggregate legitimate population.
    Consequently an aggregate-rate confidence interval would be invalid here.
    These caps only prevent catastrophic concentration in one cohort; the
    aggregate constraints remain the actual false-friction budget.
    """
    caps = constraints["scenario_caps"]
    allowance = float(caps["minimum_devices_allowance"])
    return (
        max(
            float(caps["block_multiple"])
            * float(constraints["max_legitimate_block_rate"]),
            allowance / devices,
        ),
        max(
            float(caps["review_multiple"])
            * float(constraints["max_legitimate_review_or_higher_rate"]),
            allowance / devices,
        ),
    )


def constraint_failures(
    summary: dict, scenarios: pd.DataFrame, constraints: dict
) -> list[str]:
    """Which declared friction limits a candidate breaks. Empty means eligible."""
    failures = []
    if summary["legitimate_block_rate"] > constraints["max_legitimate_block_rate"]:
        failures.append(
            f"legitimate block rate {summary['legitimate_block_rate']:.4f} > "
            f"{constraints['max_legitimate_block_rate']}"
        )
    if (
        summary["legitimate_review_or_higher_rate"]
        > constraints["max_legitimate_review_or_higher_rate"]
    ):
        failures.append(
            "legitimate review+ rate "
            f"{summary['legitimate_review_or_higher_rate']:.4f} > "
            f"{constraints['max_legitimate_review_or_higher_rate']}"
        )
    ratio = constraints["min_review_to_block_ratio"]
    if (
        summary["legitimate_block_rate"] * ratio
        > summary["legitimate_review_or_higher_rate"]
    ):
        failures.append(
            "block false positives are not materially rarer than review "
            f"(block {summary['legitimate_block_rate']:.4f}, review "
            f"{summary['legitimate_review_or_higher_rate']:.4f})"
        )
    # Per-family caps are DERIVED from the aggregate caps and the family's
    # own size, so a cap can never be tighter than a couple of devices --
    # a limit below that granularity measures sampling noise, not friction.
    for scenario, row in scenarios.loc[
        scenarios.population.eq("legitimate")
    ].iterrows():
        devices = float(row.devices)
        if devices <= 0:
            continue
        block_cap, review_cap = scenario_rate_caps(devices, constraints)
        if float(row.block_rate) > block_cap:
            failures.append(
                f"{scenario} block rate {row.block_rate:.4f} > {block_cap:.4f}"
            )
        if float(row.review_or_higher_rate) > review_cap:
            failures.append(
                f"{scenario} review+ rate {row.review_or_higher_rate:.4f} > "
                f"{review_cap:.4f}"
            )
    if (
        summary["attack_review_or_higher_recall"]
        < constraints["min_attack_review_or_higher_recall"]
    ):
        failures.append(
            "attack review+ recall "
            f"{summary['attack_review_or_higher_recall']:.4f} < "
            f"{constraints['min_attack_review_or_higher_recall']}"
        )
    return failures


#: Final tie-break among candidates that are indistinguishable on every
#: measured key. It prefers the design with more corroboration required and a
#: wider evidence vocabulary: identical behaviour here, strictly better
#: failure mode if the score distribution shifts, and a blocked customer gets
#: a concrete reason rather than "a number was high". A robustness
#: preference, not a claim that validation showed a difference.
_EVIDENCE_BREADTH = {"v2_full": 0, "v2_long_horizon": 1, "v1_like": 2}


def rank_key(row: pd.Series) -> tuple:
    """Documented ranking among eligible candidates, in this fixed order:
    catch more attackers, then block more of them, then act sooner, then
    impose less review friction."""
    return (
        -row.attack_review_or_higher_recall,
        -row.attack_block_recall,
        row.median_first_review_attempt
        if row.median_first_review_attempt is not None
        else 99.0,
        row.legitimate_review_or_higher_rate,
        _EVIDENCE_BREADTH.get(row.evidence_set, 9),
        -int(row.block_evidence),
    )


def evaluate_candidates_v2(
    frame: pd.DataFrame,
    risk: np.ndarray,
    candidates: list[dict],
    constraints: dict,
    precomputed: dict,
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    campaign = frame.campaign_active.to_numpy(dtype=bool)
    rows, scenario_tables = [], {}
    for config in candidates:
        ranks = decide_vector(
            risk,
            campaign,
            precomputed["evidence"][config["evidence_set"]],
            precomputed["trust"][config["trust_suppression"]],
            config,
        )
        devices = device_view(frame, ranks)
        summary = summarise(devices)
        scenarios = scenario_view(devices)
        failures = constraint_failures(summary, scenarios, constraints)
        label = candidate_label(config)
        scenario_tables[label] = scenarios
        rows.append(
            {
                "candidate": label,
                "review_threshold": config["review_threshold"],
                "block_threshold": config["block_threshold"],
                "block_evidence": config["block_evidence"],
                "evidence_set": config["evidence_set"],
                "trust_suppression": config["trust_suppression"],
                "campaign_review_increment": config["campaign_review_increment"],
                "campaign_block_increment": config["campaign_block_increment"],
                **summary,
                "eligible": not failures,
                "constraint_failures": "; ".join(failures),
            }
        )
    return pd.DataFrame(rows), scenario_tables


def campaign_adjustment_earns_its_place(
    with_campaign: pd.Series, without_campaign: pd.Series
) -> bool:
    """Phase 11 rule: campaign tolerance is retained only if it clearly
    improves validation WITHOUT adding friction.

    Policy v1 inherited this adjustment and it degraded on Blind v1.1 -- it
    cost 9.8pp of attack block recall inside campaigns and did not reduce
    legitimate friction. So v2 does not inherit it: it has to dominate the
    best campaign-free candidate on every axis that matters, or it is
    dropped. The generic ranking cannot express this, because its first key
    is review recall and a tolerance that shaves review friction can win
    there while losing badly on blocking.
    """
    return (
        with_campaign.attack_review_or_higher_recall
        >= without_campaign.attack_review_or_higher_recall
        and with_campaign.attack_block_recall >= without_campaign.attack_block_recall
        and with_campaign.legitimate_review_or_higher_rate
        <= without_campaign.legitimate_review_or_higher_rate
        and with_campaign.legitimate_block_rate
        <= without_campaign.legitimate_block_rate
    )


def select(candidates: pd.DataFrame) -> pd.Series:
    eligible = candidates.loc[candidates.eligible]
    if eligible.empty:
        raise RuntimeError(
            "no policy candidate satisfied the declared friction budget; "
            "loosen the constraints deliberately rather than silently"
        )
    ordered = sorted((row for _, row in eligible.iterrows()), key=rank_key)
    best = ordered[0]
    if not best.campaign_review_increment and not best.campaign_block_increment:
        return best
    campaign_free = [
        row
        for row in ordered
        if not row.campaign_review_increment and not row.campaign_block_increment
    ]
    if not campaign_free:
        return best
    if campaign_adjustment_earns_its_place(best, campaign_free[0]):
        return best
    return campaign_free[0]


def assert_engine_parity(
    frame: pd.DataFrame,
    risk: np.ndarray,
    config: dict,
    precomputed: dict,
    features: tuple[str, ...],
) -> np.ndarray:
    """The fast search path must agree with the real engine, row for row."""
    policy = RiskPolicyV2(config)
    campaign = frame.campaign_active.to_numpy(dtype=bool)
    timestamps = pd.to_datetime(frame.timestamp, format="ISO8601")
    engine_ranks = np.array(
        [
            _ORDER[
                policy.decide(
                    snapshot=snapshot,
                    risk_score=float(score),
                    timestamp=moment.to_pydatetime(),
                    campaign_active=bool(flag),
                ).action
            ]
            for snapshot, score, moment, flag in zip(
                precomputed["snapshots"], risk, timestamps, campaign, strict=True
            )
        ],
        dtype=int,
    )
    fast_ranks = decide_vector(
        risk,
        campaign,
        precomputed["evidence"][config["evidence_set"]],
        precomputed["trust"][config["trust_suppression"]],
        config,
    )
    if not np.array_equal(engine_ranks, fast_ranks):
        mismatch = int((engine_ranks != fast_ranks).sum())
        raise RuntimeError(
            f"vectorised search disagrees with RiskPolicyV2 on {mismatch} rows"
        )
    return engine_ranks


def evidence_gate_value(
    frame: pd.DataFrame, risk: np.ndarray, config: dict, precomputed: dict
) -> dict:
    """What the gate and the trust rule actually withheld.

    Diagnostic only, and the single most useful policy number Blind v1.1
    produced: without it a gate can look decorative right up until the
    distribution moves.
    """
    campaign = frame.campaign_active.to_numpy(dtype=bool)
    block_at = float(config["block_threshold"]) + np.where(
        campaign, float(config.get("campaign_block_increment", 0.0)), 0.0
    )
    high = risk >= block_at
    evidence = precomputed["evidence"][config["evidence_set"]]
    trusted = precomputed["trust"][config["trust_suppression"]]

    ungated = device_view(frame, np.where(high, 2, 0))
    gated = device_view(
        frame,
        decide_vector(risk, campaign, evidence, trusted, config),
    )
    joined = ungated[["label", "scenario"]].copy()
    joined["blocked_without_gate"] = ungated.ever_blocked
    joined["blocked_with_gate"] = gated.ever_blocked
    withheld = joined.loc[joined.blocked_without_gate & ~joined.blocked_with_gate]
    return {
        "score_only_block_candidate_attempts": int(high.sum()),
        "evidence_qualified_block_attempts": int(
            (high & (evidence >= int(config["block_evidence"])) & ~trusted).sum()
        ),
        "block_attempts_suppressed_by_gate": int(
            (high & ((evidence < int(config["block_evidence"])) | trusted)).sum()
        ),
        "attempts_at_or_above_block_threshold": int(high.sum()),
        "attempts_withheld_low_evidence": int(
            (high & (evidence < int(config["block_evidence"]))).sum()
        ),
        "attempts_withheld_trusted": int(
            (high & (evidence >= int(config["block_evidence"])) & trusted).sum()
        ),
        "devices_blocked_without_gate": int(joined.blocked_without_gate.sum()),
        "devices_blocked_with_gate": int(joined.blocked_with_gate.sum()),
        "devices_suppressed_by_gate": int(len(withheld)),
        "legitimate_blocks_prevented": int((withheld.label == 0).sum()),
        "attacks_no_longer_blocked": int((withheld.label == 1).sum()),
        "withheld_legitimate_scenarios": (
            withheld.loc[withheld.label.eq(0)].scenario.value_counts().to_dict()
        ),
        "withheld_attack_scenarios": (
            withheld.loc[withheld.label.eq(1)].scenario.value_counts().to_dict()
        ),
    }


def cost_table(devices: pd.DataFrame, costs: dict) -> dict:
    """Illustrative prototype units, reported beside the counts, never
    instead of them. Nothing was fitted to this."""
    attack = devices.loc[devices.label.eq(1)]
    legitimate = devices.loc[devices.label.eq(0)]
    counts = {
        "legitimate_allow": int((~legitimate.ever_reviewed).sum()),
        "legitimate_review": int(
            (legitimate.ever_reviewed & ~legitimate.ever_blocked).sum()
        ),
        "legitimate_block": int(legitimate.ever_blocked.sum()),
        "attack_allow": int((~attack.ever_reviewed).sum()),
        "attack_review": int((attack.ever_reviewed & ~attack.ever_blocked).sum()),
        "attack_block": int(attack.ever_blocked.sum()),
    }
    return {
        "units": "illustrative prototype units, not Razorpay economics",
        "counts": counts,
        "total": round(sum(counts[name] * float(costs[name]) for name in counts), 2),
    }
