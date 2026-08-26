from fastapi import APIRouter

from card_testing_sentinel.api.dependencies import RuntimeDependency
from card_testing_sentinel.domain.exceptions import RuntimeStateError

router = APIRouter(prefix="/api/metrics")


def _median(block: dict | None) -> int | None:
    if not isinstance(block, dict) or block.get("median") is None:
        return None
    return int(block["median"])


def _limitations(metrics: dict) -> list[str]:
    """Build the mandatory disclosure list from the frozen artifact values."""
    integrity = metrics["dataset_integrity"]
    policy = metrics["operational_policy"]
    extended = metrics.get("extended_operational_metrics", {})
    audit = metrics.get("audit", {})
    review_median = _median(extended.get("attempts_scored_through_first_review"))
    block_median = _median(extended.get("attempts_scored_through_first_block"))
    preventable = policy.get(
        "potentially_preventable_later_attempts_offline_upper_bound"
    )
    lines = [
        "All results come from synthetic data and do not establish "
        "performance on real merchant traffic.",
        "No attacker was detected within the first three attempts "
        f"({audit.get('blind_detected_within_three_attempts', 0)} of "
        f"{integrity['attacker_devices']}).",
    ]
    if review_median is not None:
        lines.append(f"Median first review happened at attempt {review_median}.")
    if block_median is not None:
        lines.append(f"Median first block happened at attempt {block_median}.")
    lines.append(
        f"{policy['never_detected_attackers']} of {integrity['attacker_devices']} "
        "blind attackers were never detected."
    )
    lines.append(
        "Patient and evasive behaviour remains harder to catch than burst behaviour."
    )
    lines.append("The risk score is not a guaranteed fraud probability.")
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
        "limitations": _limitations(metrics),
        "warning": "Frozen synthetic blind replay; these rows are never rescored.",
    }
