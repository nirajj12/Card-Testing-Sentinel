"""Blind replay availability without regeneration or rescoring."""

from fastapi import APIRouter

router = APIRouter(prefix="/api/replay")

_NOT_PACKAGED = {
    "status": "not_packaged",
    "reason": (
        "Exact Blind v2 device timelines are not packaged in the repository. "
        "Frozen aggregate evidence remains available at /api/metrics/blind."
    ),
    "missing_artifact": "data/generated/blind_v2/raw_events.csv",
    "regeneration_allowed": False,
    "rescoring_allowed": False,
}


@router.get("/devices")
def devices() -> dict:
    return dict(_NOT_PACKAGED)


@router.get("/devices/{device_id}/timeline")
def timeline(device_id: str) -> dict:
    return {**_NOT_PACKAGED, "device_id": device_id}
