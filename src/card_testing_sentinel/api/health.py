from fastapi import APIRouter, Response, status

from card_testing_sentinel.api.dependencies import RuntimeDependency

router = APIRouter()


@router.get("/health/live")
def live() -> dict:
    return {"status": "live"}


@router.get("/health/ready")
def ready(runtime: RuntimeDependency, response: Response) -> dict:
    if not runtime.ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "status": "ready" if runtime.ready else "not_ready",
        "ready": runtime.ready,
        "error": runtime.startup_error,
    }


@router.get("/api/system")
def system(runtime: RuntimeDependency) -> dict:
    if not runtime.ready or runtime.registry is None or runtime.service is None:
        return {"ready": False, "error": runtime.startup_error}
    return {
        "ready": True,
        **runtime.registry.system_summary(),
        "database": runtime.service.repository.status(),
        "ordering": "per-device-and-customer (timestamp, event_sequence)",
        "razorpay": (
            runtime.razorpay.public_status
            if runtime.razorpay is not None
            else {"configured": False, "mode": "unavailable"}
        ),
    }
