from fastapi import APIRouter, HTTPException

from card_testing_sentinel.v2.phase4.contracts import DemoStartRequest, DemoStepRequest
from card_testing_sentinel.v2.phase4.dependencies import (
    Phase4Runtime,
    RuntimeDependency,
)

router = APIRouter(prefix="/api/v2/demo")


def _demo(runtime: Phase4Runtime):
    if runtime.demo is None:
        raise HTTPException(status_code=404, detail="demo mode is disabled")
    return runtime.demo


@router.get("/scenarios")
def scenarios(runtime: RuntimeDependency) -> dict:
    return {"items": _demo(runtime).scenarios()}


@router.post("/start")
def start(payload: DemoStartRequest, runtime: RuntimeDependency) -> dict:
    return _demo(runtime).start(payload.scenario)


@router.post("/step")
async def step(payload: DemoStepRequest, runtime: RuntimeDependency) -> dict:
    try:
        return await _demo(runtime).step(payload.demo_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="demo session not found") from error


@router.post("/reset")
def reset(runtime: RuntimeDependency) -> dict:
    return _demo(runtime).reset()
