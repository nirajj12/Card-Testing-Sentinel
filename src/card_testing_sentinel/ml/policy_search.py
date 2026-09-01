"""Validation-only operating-point selection.

Replays the frozen model's validation scores through candidate policies,
device by device in time order, and reports device-level friction and
detection for each. The model is never refitted and validation is the only
split touched -- no blind data exists.

Selection is constraint-first: a candidate is eligible only if it stays
inside the false-friction budget declared in ``configs/policy.yaml`` *before*
any candidate is scored. Among eligible candidates, the ranking objective is
documented and applied in a fixed order. Maximising recall alone is exactly
the failure mode this design exists to avoid.
"""

from __future__ import annotations

from datetime import datetime
from itertools import product

import numpy as np
import pandas as pd

from card_testing_sentinel.features.specification import MODEL_FEATURES
from card_testing_sentinel.policy.engine import DeviceRiskHistory, RiskPolicy

ACTIONS = ("allow", "review", "block")
_ORDER = {"allow": 0, "review": 1, "block": 2}


def replay(frame: pd.DataFrame, risk: np.ndarray, policy: RiskPolicy) -> pd.DataFrame:
    """Score every validation attempt through one policy, per device in order.

    A block does not suppress later attempts: in the real service a blocked
    request simply never becomes a Razorpay order, and the *next* request is
    scored again from current history. Replaying every attempt is therefore
    the honest measurement -- and it is also conservative, because a real
    block would have prevented some of the later attempts we still count.
    """
    working = frame[
        ["device_id", "label", "scenario", "population", "merchant_kind"]
    ].copy()
    working["timestamp"] = pd.to_datetime(frame.timestamp, format="ISO8601")
    working["risk"] = np.asarray(risk, dtype=float)
    working["campaign_active"] = frame["campaign_active"].to_numpy(dtype=bool)
    snapshots = frame.loc[:, list(MODEL_FEATURES)].to_dict("records")
    working["row_index"] = range(len(working))
    working = working.sort_values(["device_id", "timestamp"], kind="mergesort")

    histories: dict[str, DeviceRiskHistory] = {}
    actions, attempts, expiries = [], [], []
    counter: dict[str, int] = {}
    for row in working.itertuples():
        history = histories.setdefault(row.device_id, DeviceRiskHistory())
        moment: datetime = row.timestamp.to_pydatetime()
        decision = policy.decide(
            snapshot=snapshots[row.row_index],
            risk_score=float(row.risk),
            timestamp=moment,
            campaign_active=bool(row.campaign_active),
            history=history,
        )
        history.record(
            moment, float(row.risk), policy.persistence_window, policy.history_cap
        )
        counter[row.device_id] = counter.get(row.device_id, 0) + 1
        actions.append(decision.action)
        attempts.append(counter[row.device_id])
        expiries.append(decision.block_expires_at)

    working["action"] = actions
    working["attempt"] = attempts
    working["block_expires_at"] = expiries
    return working


def device_view(replayed: pd.DataFrame) -> pd.DataFrame:
    """One row per device: did it ever get reviewed / blocked, and when."""
    replayed = replayed.copy()
    replayed["rank"] = replayed.action.map(_ORDER)
    first_review = (
        replayed.loc[replayed["rank"] >= 1].groupby("device_id").attempt.min()
    )
    first_block = replayed.loc[replayed["rank"] >= 2].groupby("device_id").attempt.min()
    view = replayed.groupby("device_id").agg(
        label=("label", "first"),
        scenario=("scenario", "first"),
        population=("population", "first"),
        merchant_kind=("merchant_kind", "first"),
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
    }


def _quantile(series: pd.Series, q: float) -> float | None:
    clean = series.dropna()
    return float(clean.quantile(q)) if len(clean) else None


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


# --------------------------------------------------------------------------
# candidate grid
# --------------------------------------------------------------------------


def candidate_configs(search: dict, base: dict) -> list[dict]:
    """Build the policy grid declared in config. Small and readable by
    design: a hundred arbitrary decimals would just be fitting the search."""
    candidates: list[dict] = []
    reviews = [round(float(v), 3) for v in search["review_thresholds"]]
    blocks = [round(float(v), 3) for v in search["block_thresholds"]]
    campaigns = [
        (round(float(r), 3), round(float(b), 3))
        for r, b in search.get("campaign_increments", [[0.0, 0.0]])
    ]

    for review, block in product(reviews, blocks):
        if block <= review:
            continue
        for campaign_review, campaign_block in campaigns:
            shared = {
                **base,
                "review_threshold": review,
                "block_threshold": block,
                "campaign_review_increment": campaign_review,
                "campaign_block_increment": campaign_block,
            }
            candidates.append({**shared, "family": "threshold", "block_evidence": 0})
            for evidence in search["block_evidence_counts"]:
                candidates.append(
                    {
                        **shared,
                        "family": "evidence_gated",
                        "block_evidence": int(evidence),
                    }
                )
            for elevated in search["block_elevated_counts"]:
                for evidence in search["persistent_block_evidence_counts"]:
                    candidates.append(
                        {
                            **shared,
                            "family": "persistent",
                            "block_elevated_count": int(elevated),
                            "block_evidence": int(evidence),
                        }
                    )
    return candidates


def candidate_label(config: dict) -> str:
    parts = [
        config["family"],
        f"R{config['review_threshold']:.2f}",
        f"B{config['block_threshold']:.2f}",
    ]
    if config["family"] == "evidence_gated":
        parts.append(f"E{config['block_evidence']}")
    if config["family"] == "persistent":
        parts.append(f"N{config['block_elevated_count']}E{config['block_evidence']}")
    if config.get("campaign_review_increment") or config.get(
        "campaign_block_increment"
    ):
        parts.append(
            f"C{config['campaign_review_increment']:.2f}"
            f"/{config['campaign_block_increment']:.2f}"
        )
    return "_".join(parts)


# --------------------------------------------------------------------------
# constraints and ranking
# --------------------------------------------------------------------------


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
            f"legitimate review+ rate "
            f"{summary['legitimate_review_or_higher_rate']:.4f} > "
            f"{constraints['max_legitimate_review_or_higher_rate']}"
        )
    # A block stops a payment; a review does not. The gap must be real.
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
    for scenario, cap in constraints["max_scenario_block_rate"].items():
        if scenario not in scenarios.index:
            continue
        observed = float(scenarios.loc[scenario, "block_rate"])
        if observed > float(cap):
            failures.append(f"{scenario} block rate {observed:.4f} > {cap}")
    for scenario, cap in constraints.get("max_scenario_review_rate", {}).items():
        if scenario not in scenarios.index:
            continue
        observed = float(scenarios.loc[scenario, "review_or_higher_rate"])
        if observed > float(cap):
            failures.append(f"{scenario} review+ rate {observed:.4f} > {cap}")
    if (
        summary["attack_review_or_higher_recall"]
        < constraints["min_attack_review_or_higher_recall"]
    ):
        failures.append(
            f"attack review+ recall "
            f"{summary['attack_review_or_higher_recall']:.4f} < "
            f"{constraints['min_attack_review_or_higher_recall']}"
        )
    return failures


#: Final tie-break, applied only when candidates are indistinguishable on
#: every measured ranking key. It prefers the *stronger block gate*: a block
#: that additionally requires corroborating evidence has the same measured
#: behaviour here but a strictly better failure mode if the score
#: distribution ever shifts, and it gives a blocked customer a concrete
#: reason beyond "a number was high". This is a robustness preference, not a
#: claim that validation showed a difference.
_GATE_STRENGTH = {"evidence_gated": 0, "persistent": 1, "threshold": 2}


def rank_key(row: pd.Series) -> tuple:
    """Documented ranking, applied in this fixed order among eligible
    candidates: catch more attackers, then block more of them, then act
    sooner, then impose less review friction. `_GATE_STRENGTH` breaks
    remaining exact ties deterministically."""
    return (
        -row.attack_review_or_higher_recall,
        -row.attack_block_recall,
        row.median_first_review_attempt
        if row.median_first_review_attempt is not None
        else 99.0,
        row.legitimate_review_or_higher_rate,
        _GATE_STRENGTH.get(row.family, 9),
        -int(row.block_evidence),
    )


def evaluate_candidates(
    frame: pd.DataFrame,
    risk: np.ndarray,
    candidates: list[dict],
    constraints: dict,
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    rows, scenario_tables = [], {}
    for config in candidates:
        policy = RiskPolicy(config)
        devices = device_view(replay(frame, risk, policy))
        summary = summarise(devices)
        scenarios = scenario_view(devices)
        failures = constraint_failures(summary, scenarios, constraints)
        label = candidate_label(config)
        scenario_tables[label] = scenarios
        rows.append(
            {
                "candidate": label,
                "family": config["family"],
                "review_threshold": config["review_threshold"],
                "block_threshold": config["block_threshold"],
                "block_evidence": config.get("block_evidence", 0),
                "block_elevated_count": config.get("block_elevated_count", 1),
                "campaign_review_increment": config.get(
                    "campaign_review_increment", 0.0
                ),
                "campaign_block_increment": config.get("campaign_block_increment", 0.0),
                **summary,
                "eligible": not failures,
                "constraint_failures": "; ".join(failures),
            }
        )
    return pd.DataFrame(rows), scenario_tables


def select(candidates: pd.DataFrame) -> pd.Series:
    eligible = candidates.loc[candidates.eligible]
    if eligible.empty:
        raise RuntimeError(
            "no policy candidate satisfied the declared friction budget; "
            "loosen the constraints deliberately rather than silently"
        )
    ordered = sorted(
        (row for _, row in eligible.iterrows()),
        key=rank_key,
    )
    return ordered[0]


# --------------------------------------------------------------------------
# illustrative cost comparison
# --------------------------------------------------------------------------


def cost_table(devices: pd.DataFrame, costs: dict) -> dict:
    """A secondary, clearly illustrative comparison.

    These are prototype units invented for ordering the options, NOT Razorpay
    economics and not money. They are reported alongside the counts, never
    instead of them, and were not used to fit anything.
    """
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
    total = sum(counts[name] * float(costs[name]) for name in counts)
    return {
        "units": "illustrative prototype units, not Razorpay economics",
        "weights": dict(costs),
        "counts": counts,
        "total_cost": round(total, 2),
        "cost_per_device": round(total / max(len(devices), 1), 4),
    }
