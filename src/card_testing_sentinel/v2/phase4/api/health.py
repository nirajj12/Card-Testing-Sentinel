from fastapi import APIRouter

from card_testing_sentinel.v2.phase4.dependencies import RuntimeDependency

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


@router.get("/api/v2/system")
def system(runtime: RuntimeDependency) -> dict:
    if not runtime.ready or runtime.registry is None or runtime.service is None:
        return {"ready": False, "error": runtime.startup_error}
    return {
        "ready": True,
        **runtime.registry.system_summary(),
        "database": runtime.service.repository.status(),
        "concurrency": "global asynchronous transition lock",
    }
