from __future__ import annotations

import math
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from card_testing_sentinel.v2.phase4.dependencies import RuntimeDependency
from card_testing_sentinel.v2.phase4.exceptions import RuntimeStateError

router = APIRouter(prefix="/api/v2/replay")


def _safe(value):
    if isinstance(value, float) and math.isnan(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


@router.get("/devices")
def devices(
    runtime: RuntimeDependency,
    population: str | None = None,
    attack_subtype: str | None = None,
    decision: str | None = None,
    detected: bool | None = None,
    first_review_attempt: Annotated[int | None, Query(ge=1)] = None,
    first_block_attempt: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict:
    if not runtime.ready or runtime.registry is None:
        raise RuntimeStateError("application is not ready")
    frame = runtime.registry.blind_devices.copy()
    if population:
        frame = frame.loc[frame.population.eq(population)]
    if attack_subtype:
        frame = frame.loc[frame.attack_subtype.eq(attack_subtype)]
    if decision == "block":
        frame = frame.loc[frame.blocked]
    elif decision == "review":
        frame = frame.loc[frame.review_or_higher & ~frame.blocked]
    elif decision == "allow":
        frame = frame.loc[~frame.review_or_higher]
    if detected is not None:
        frame = frame.loc[frame.review_or_higher.eq(detected)]
    if first_review_attempt is not None:
        frame = frame.loc[frame.first_review_or_higher_request.eq(first_review_attempt)]
    if first_block_attempt is not None:
        frame = frame.loc[frame.first_block_request.eq(first_block_attempt)]
    records = [
        {key: _safe(value) for key, value in row.items()}
        for row in frame.head(limit).to_dict("records")
    ]
    return {"items": records, "count": len(records), "rescored": False}


@router.get("/devices/{device_id}/timeline")
def timeline(device_id: str, runtime: RuntimeDependency) -> dict:
    if not runtime.ready or runtime.registry is None:
        raise RuntimeStateError("application is not ready")
    frame = runtime.registry.blind_decisions
    rows = frame.loc[frame.device_id.eq(device_id)].sort_values("request_index")
    if rows.empty:
        raise HTTPException(status_code=404, detail="blind replay device not found")
    safe_rows = [
        {key: _safe(value) for key, value in row.items()}
        for row in rows.to_dict("records")
    ]
    return {"device_id": device_id, "items": safe_rows, "rescored": False}
