import json

from fastapi import APIRouter

from card_testing_sentinel.v2.phase4.dependencies import RuntimeDependency
from card_testing_sentinel.v2.phase4.exceptions import RuntimeStateError

router = APIRouter(prefix="/api/v2/metrics")


@router.get("/blind")
def blind_metrics(runtime: RuntimeDependency) -> dict:
    if not runtime.ready or runtime.registry is None:
        raise RuntimeStateError("application is not ready")
    metrics = runtime.registry.blind_metrics
    return {
        "status": metrics["status"],
        "policy_id": metrics["policy_id"],
        "dataset_integrity": metrics["dataset_integrity"],
        "operational_policy": metrics["operational_policy"],
        "action_counts": metrics["action_counts"],
        "runtime": {
            "per_request_scoring_latency": metrics["online_batch_parity"],
        },
        "recorded_runtime": json.loads(
            (
                runtime.registry.root / "artifacts/v2/phase3/blind/runtime.json"
            ).read_text()
        ),
        "warning": "Frozen synthetic blind replay; these rows are never rescored.",
    }
