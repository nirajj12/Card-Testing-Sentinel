from fastapi import APIRouter

router = APIRouter(prefix="/api/replay")

_UNAVAILABLE = {
    "status": "unavailable",
    "reason": "Dataset V2 model and blind evaluation have not been generated yet.",
}


@router.get("/devices")
def devices() -> dict:
    return dict(_UNAVAILABLE)


@router.get("/devices/{device_id}/timeline")
def timeline(device_id: str) -> dict:
    return dict(_UNAVAILABLE)
