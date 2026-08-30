from fastapi import APIRouter

from card_testing_sentinel.api.dependencies import RuntimeDependency
from card_testing_sentinel.domain.exceptions import RuntimeStateError

router = APIRouter(prefix="/api/metrics")


def _median(block: dict | None) -> int | None:
    if not isinstance(block, dict) or block.get("median") is None:
        return None
    return int(block["median"])


#: Operator-facing names for the frozen legitimate populations. Display only --
#: the keys themselves come from the frozen artifact and are never renamed there.
_POPULATION_LABELS = {
    "normal_standard": "Everyday checkout",
    "normal_bad_luck": "Bad-luck retry",
    "flash_standard": "Flash sale",
    "flash_hard_retry": "Flash-sale hard retry",
}
_SUBTYPE_LABELS = {
    "burst": "Burst card testing",
    "evasive": "Evasive card testing",
    "patient": "Patient card testing",
}


def _legitimate_impact(metrics: dict) -> dict:
    """Where the friction actually landed, per legitimate population.

    "0 of 1,700 blocked" on its own is close to structurally guaranteed here,
    because most legitimate devices in this synthetic set never make enough
    attempts to reach a multi-score block. The informative number is which
    populations absorbed the two reviews -- so it is reported alongside,
    never instead of, the headline count.
    """
    policy = metrics["operational_policy"]
    integrity = metrics["dataset_integrity"]
    budgets = policy.get("budget_results", {})
    populations = [
        {
            "population": name,
            "label": _POPULATION_LABELS.get(name, name),
            "devices": int(budget["denominator_devices"]),
            "reviewed": int(budget.get("review_or_higher_devices", 0)),
            "blocked": int(budget.get("block_devices", 0)),
        }
        for name, budget in sorted(budgets.items())
        if name != "overall_legitimate"
    ]
    return {
        "devices": integrity["legitimate_devices"],
        "reviewed": policy["legitimate_review_or_higher"],
        "blocked": policy["legitimate_blocks"],
        "by_population": populations,
    }


def _failure_modes(metrics: dict) -> dict:
    """The misses, reported as first-class output rather than a footnote."""
    policy = metrics["operational_policy"]
    integrity = metrics["dataset_integrity"]
    audit = metrics.get("audit", {})
    subtypes = policy.get("subtype", {})
    return {
        "attacker_devices": integrity["attacker_devices"],
        "never_detected": policy["never_detected_attackers"],
        "detected_within_three_attempts": audit.get(
            "blind_detected_within_three_attempts", 0
        ),
        "by_subtype": [
            {
                "subtype": name,
                "label": _SUBTYPE_LABELS.get(name, name),
                "devices": int(block["review_or_higher"]["denominator"]),
                "review_or_higher_rate": block["review_or_higher"]["rate"],
                "block_rate": block["block"]["rate"],
                "never_detected": int(block.get("never_detected", 0)),
            }
            for name, block in sorted(subtypes.items())
        ],
    }


def _limitations(metrics: dict) -> list[str]:
    """The disclosures that are not already stated elsewhere on the page.

    Detection latency, the never-detected count and the per-subtype gaps are
    served as first-class metrics (`detection_latency`, `failure_modes`) and
    rendered in their own section. Repeating them here made the list read as
    a wall and buried the disclosures that appear nowhere else.
    """
    integrity = metrics["dataset_integrity"]
    policy = metrics["operational_policy"]
    preventable = policy.get(
        "potentially_preventable_later_attempts_offline_upper_bound"
    )
    budgets = policy.get("budget_results", {})
    borderline = sum(
        int(budgets.get(name, {}).get("denominator_devices", 0))
        for name in ("normal_bad_luck", "flash_hard_retry")
    )
    lines = [
        "Legitimate devices in this synthetic evaluation generally generate "
        "few attempts, so most never reach the policy's multi-score block "
        "requirement. The more informative legitimate test is therefore the "
        f"{borderline} borderline retry and hard-retry devices rather than "
        "the raw zero-block count alone.",
        "All results come from synthetic data and do not establish "
        f"performance on real merchant traffic. The {integrity['devices']} "
        "evaluated devices were generated, not observed.",
        "The risk score is a calibrated ranking, not a guaranteed fraud "
        "probability.",
    ]
    if preventable is not None:
        lines.append(
            f"The {preventable:,} potentially preventable attempts are an offline "
            "replay upper bound, not observed fraud prevention."
        )
    lines.append(
        "Local SQLite with a single process is a prototype, not a production "
        "payment network."
    )
    lines.append(
        "A real deployment needs merchant data, monitoring, drift detection and "
        "human-review feedback."
    )
    return lines


@router.get("/blind")
def blind_metrics(runtime: RuntimeDependency) -> dict:
    if not runtime.ready or runtime.registry is None:
        raise RuntimeStateError("application is not ready")
    metrics = runtime.registry.blind_metrics
    integrity = metrics["dataset_integrity"]
    extended = metrics.get("extended_operational_metrics", {})
    return {
        "status": metrics["status"],
        "policy_id": "operational-policy-1",
        "dataset_integrity": integrity,
        "operational_policy": metrics["operational_policy"],
        "action_counts": metrics["action_counts"],
        "runtime": {"online_batch_parity": metrics["online_batch_parity"]},
        "denominators": {
            "legitimate_devices": integrity["legitimate_devices"],
            "attacker_devices": integrity["attacker_devices"],
            "devices": integrity["devices"],
            "authorization_requests": integrity["authorization_requests"],
        },
        "detection_latency": {
            "median_first_review_attempt": _median(
                extended.get("attempts_scored_through_first_review")
            ),
            "median_first_block_attempt": _median(
                extended.get("attempts_scored_through_first_block")
            ),
        },
        "legitimate_impact": _legitimate_impact(metrics),
        "failure_modes": _failure_modes(metrics),
        "baseline_comparison": runtime.registry.baseline_comparison,
        "limitations": _limitations(metrics),
        "warning": "Frozen synthetic blind replay; these rows are never rescored.",
    }
