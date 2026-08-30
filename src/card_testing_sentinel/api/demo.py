from fastapi import APIRouter, HTTPException

from card_testing_sentinel.api.contracts import (
    DemoStartRequest,
    DemoStepRequest,
    TrafficStartRequest,
    TrafficStepRequest,
    TrafficTruthRequest,
)
from card_testing_sentinel.api.dependencies import (
    ApplicationRuntime,
    RuntimeDependency,
)

router = APIRouter(prefix="/api/demo")


def _demo(runtime: ApplicationRuntime):
    # A startup failure (e.g. an incompatible runtime that never loaded the
    # model) must surface as "not ready", not as a generic 404. Otherwise a
    # client sees "demo mode is disabled" and has no way to tell a real
    # startup failure apart from demo mode simply being turned off in
    # config, and a request built from an empty scenario list can go on to
    # fail with an unrelated 422.
    if not runtime.ready:
        raise HTTPException(
            status_code=503,
            detail=runtime.startup_error or "runtime is not ready",
        )
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


@router.post("/traffic/start")
def traffic_start(payload: TrafficStartRequest, runtime: RuntimeDependency) -> dict:
    """Begin a mixed merchant-traffic run.

    The operator starts traffic; they do not choose who is in it. The only
    accepted input is an optional seed, which reproduces a previous run for
    inspection. The detector still meets every device cold.
    """
    return _demo(runtime).start_traffic(payload.seed)


@router.post("/traffic/step")
async def traffic_step(payload: TrafficStepRequest, runtime: RuntimeDependency) -> dict:
    try:
        return await _demo(runtime).step_traffic(payload.traffic_run_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="traffic run not found") from error


@router.post("/traffic/truth")
def traffic_truth(payload: TrafficTruthRequest, runtime: RuntimeDependency) -> dict:
    """Reveal what the simulator knew, strictly after the fact.

    This is a separate, explicitly-requested call rather than a field on the
    step response, so ground truth never travels alongside a decision.
    """
    try:
        return _demo(runtime).traffic_truth(payload.traffic_run_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="traffic run not found") from error


@router.post("/reset")
def reset(runtime: RuntimeDependency) -> dict:
    return _demo(runtime).reset()
