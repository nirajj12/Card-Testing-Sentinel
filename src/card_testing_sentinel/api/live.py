from typing import Annotated

from fastapi import APIRouter, Query

from card_testing_sentinel.api.contracts import (
    PrecheckRequest,
    PrecheckResponse,
)
from card_testing_sentinel.api.dependencies import (
    ApplicationRuntime,
    RuntimeDependency,
)
from card_testing_sentinel.domain.exceptions import RuntimeStateError

router = APIRouter(prefix="/api")


def _service(runtime: ApplicationRuntime):
    if not runtime.ready or runtime.service is None:
        raise RuntimeStateError("application is not ready")
    return runtime.service


@router.post("/precheck", response_model=PrecheckResponse)
async def precheck(
    payload: PrecheckRequest, runtime: RuntimeDependency
) -> PrecheckResponse:
    return await _service(runtime).precheck(payload)


@router.get("/runtime/decisions")
def decisions(
    runtime: RuntimeDependency,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict:
    return {"items": _service(runtime).decisions(limit)}


@router.get("/activity/recent")
def recent_activity(
    runtime: RuntimeDependency,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict:
    if not runtime.ready or runtime.razorpay is None:
        raise RuntimeStateError("application is not ready")
    return {"items": runtime.razorpay.recent_activity(limit)}


@router.get("/runtime/devices/{device_id}/timeline")
def timeline(device_id: str, runtime: RuntimeDependency) -> dict:
    return {
        "device_reference": device_id,
        "items": _service(runtime).timeline(device_id),
    }
