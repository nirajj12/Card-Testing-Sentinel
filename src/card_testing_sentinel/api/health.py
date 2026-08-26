from fastapi import APIRouter

from card_testing_sentinel.api.dependencies import RuntimeDependency

router = APIRouter()


@router.get("/health/live")
def live() -> dict:
    return {"status": "live"}


@router.get("/health/ready")
def ready(runtime: RuntimeDependency) -> dict:
    return {
        "status": "ready" if runtime.ready else "not_ready",
        "ready": runtime.ready,
        "error": runtime.startup_error,
    }


@router.get("/api/system")
def system(runtime: RuntimeDependency) -> dict:
    if not runtime.ready or runtime.registry is None or runtime.service is None:
        payload: dict = {"ready": False, "error": runtime.startup_error}
        if runtime.compatibility_report is not None:
            payload["compatibility"] = runtime.compatibility_report
        return payload
    return {
        "ready": True,
        **runtime.registry.system_summary(),
        "database": runtime.service.repository.status(),
        "concurrency": "global asynchronous transition lock",
    }
