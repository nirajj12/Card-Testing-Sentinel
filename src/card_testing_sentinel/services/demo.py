"""Demo orchestration driving the real production RiskService.

This intentionally does not construct a second scoring path, a second
feature engine, a second policy, or a second (in-memory) repository. It is
handed the *same* RiskService instance -- backed by the same
SQLite repository -- that live `/api/precheck` traffic uses, and drives it
through real precheck/outcome/checkout transitions with uniquely
namespaced synthetic identifiers per run.

These lifecycle transitions are server-generated simulation data, not browser-
submitted or Razorpay-verified outcomes. The fixed ``demo-merchant`` plus
per-run device, session, and IP namespaces keep their feature history separate
from the real Test Mode checkout merchant. The normal live router exposes no
direct outcome or checkout-completion write endpoint.

Two orchestration modes share one drive path (`_drive_attempt`):

* **Replay Lab** (`start` / `step`) -- one device walking one hand-authored
  scenario plan, stepped manually. This is the controlled teaching mode.
* **Live Traffic** (`start_traffic` / `step_traffic`) -- many independent
  devices from `services.traffic_simulation`, merge-sorted onto one virtual
  clock and emitted in globally non-decreasing `(timestamp, event_sequence)`
  order. This is the product mode: the operator starts traffic and the
  detector meets each device cold.

**Ground-truth isolation.** The simulator knows which scenario each device
is running. The risk engine never does: a scenario key is not a field of
`PrecheckRequest` (which sets `extra="forbid"`), it is not in any identifier
this module builds, and it never reaches feature computation, the model or
the policy. It is also deliberately *not* returned alongside a decision --
`traffic_truth()` is a separate call the operator must make explicitly,
after the fact, so the reveal cannot be confused with something the detector
was given.

`reset()` only clears this manager's in-memory run bookkeeping. It never
touches the shared repository, so it can never erase persisted audit history.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from card_testing_sentinel.api.contracts import (
    CheckoutRequest,
    OutcomeRequest,
    PrecheckRequest,
)
from card_testing_sentinel.security.identifiers import IdentifierProtector
from card_testing_sentinel.services.operations_projection import build_projection
from card_testing_sentinel.services.risk_service import RiskService
from card_testing_sentinel.services.scenario_generation import (
    SCENARIO_CATALOG,
    SCENARIO_PLANS,
    PlannedAttempt,
)
from card_testing_sentinel.services.traffic_simulation import (
    ScheduledAttempt,
    TrafficDevice,
    new_seed,
    schedule_for,
)

_OUTCOME_LAG_SECONDS = 1
_CHECKOUT_LAG_SECONDS = 30
_DEMO_CURRENCY = "INR"
_DEMO_MERCHANT = "demo-merchant"


@dataclass
class DemoRun:
    run_id: str
    scenario: str
    anchor: datetime
    sequence: int = 0
    index: int = 0
    checkout_sent: bool = False
    #: cumulative seconds from `anchor` to the most recently processed
    #: attempt -- each PlannedAttempt.gap_seconds is a delta *since the
    #: previous attempt*, not an absolute offset, so this must accumulate.
    elapsed_seconds: int = 0


@dataclass
class TrafficDeviceState:
    """Per-device bookkeeping for one live-traffic run.

    ``scenario`` lives here, on the *simulator* side of the boundary, and is
    only ever read by `traffic_truth()` after decisions already exist.
    """

    device: TrafficDevice
    checkout_sent: bool = False
    attempts: list[dict] = field(default_factory=list)


@dataclass
class TrafficRun:
    run_id: str
    seed: int
    anchor: datetime
    schedule: tuple[ScheduledAttempt, ...]
    devices: dict[str, TrafficDeviceState]
    #: One monotonic counter shared by every device in the run. The
    #: repository's late-event check is global, not per device, so per-device
    #: counters restarting at zero would regress the global order.
    sequence: int = 0
    index: int = 0
    #: Follow-up lifecycle events (outcome, checkout) that are due at a later
    #: virtual offset than the attempt that created them. Flushed in offset
    #: order before any attempt scheduled at or after them is emitted.
    pending: list[tuple[int, int, dict]] = field(default_factory=list)
    #: Monotonic tiebreaker so two follow-ups due at the same virtual offset
    #: keep the order they were created in. Separate from `sequence`, which
    #: is the real event-ordering counter handed to the service.
    pending_seq: int = 0
    counts: dict[str, int] = field(
        default_factory=lambda: {"allow": 0, "review": 0, "block": 0}
    )


class DemoManager:
    def __init__(self, service: RiskService, protector: IdentifierProtector):
        self.service = service
        self.protector = protector
        self.runs: dict[str, DemoRun] = {}
        self.traffic_runs: dict[str, TrafficRun] = {}

    def scenarios(self) -> list[dict]:
        return [
            {"id": name, "label": spec["label"], "attempts": spec["attempts"]}
            for name, spec in SCENARIO_CATALOG.items()
        ]

    def _clock_anchor(self) -> datetime:
        # Ordering is per device, and every run uses a fresh namespace (so a
        # fresh device hash). A run's devices are therefore independent of
        # anything already persisted and cannot be "late" against it.
        return datetime.now(UTC)

    # ------------------------------------------------------------------
    # Shared drive path
    # ------------------------------------------------------------------

    async def _drive_attempt(
        self,
        *,
        namespace: str,
        device_key: str,
        anchor: datetime,
        offset_seconds: int,
        attempt: int,
        spec: PlannedAttempt,
        next_sequence,
        checkout_already_sent: bool,
    ) -> dict:
        """Run one attempt through the real service and project the result.

        `next_sequence` is a callable so the caller owns the counter: a
        Replay Lab run keeps its own, while a live-traffic run shares one
        monotonic counter across every device it drives.

        Returns the projection plus any follow-up lifecycle events that are
        due *later* on the virtual clock, so the caller can schedule them in
        globally correct order instead of emitting them immediately.
        """
        device_id = f"{namespace}_device"
        session_id = f"{namespace}_{spec.session_suffix}"
        ip_reference = f"{namespace}_{spec.ip_suffix}"
        request_id = f"{namespace}_request_{attempt}"

        precheck_timestamp = anchor + timedelta(seconds=offset_seconds)
        precheck_request = PrecheckRequest(
            request_id=request_id,
            event_id=f"{namespace}_precheck_{attempt}",
            merchant_id=_DEMO_MERCHANT,
            device_id=device_id,
            session_id=session_id,
            ip_reference=ip_reference,
            amount=spec.amount,
            currency=_DEMO_CURRENCY,
            timestamp=precheck_timestamp,
            event_sequence=next_sequence(),
            campaign_active=spec.campaign_active,
        )
        response, evidence = await self.service.precheck_with_evidence(precheck_request)

        blocked = response.decision == "block"
        follow_ups: list[tuple[int, dict]] = []
        if not blocked:
            follow_ups.append(
                (
                    offset_seconds + _OUTCOME_LAG_SECONDS,
                    {
                        "kind": "outcome",
                        "namespace": namespace,
                        "device_key": device_key,
                        "request_id": request_id,
                        "device_id": device_id,
                        "session_id": session_id,
                        "attempt": attempt,
                        "authorization_result": spec.authorization_result,
                        "failure_reason": spec.failure_reason,
                        "card_last4": spec.outcome_card_last4,
                        "card_network": spec.outcome_card_network,
                    },
                )
            )
            if spec.authorization_result == "approved" and not checkout_already_sent:
                follow_ups.append(
                    (
                        offset_seconds + _CHECKOUT_LAG_SECONDS,
                        {
                            "kind": "checkout",
                            "namespace": namespace,
                            "device_key": device_key,
                            "request_id": request_id,
                            "device_id": device_id,
                            "session_id": session_id,
                            "attempt": attempt,
                        },
                    )
                )

        projection = build_projection(
            decision=response.decision,
            risk_score=response.risk_score,
            rule_score=response.rule_score,
            reason_codes=response.reason_codes,
            state_version=response.device_state_version,
            latency_ms=response.latency_ms,
            idempotent_replay=response.idempotent_replay,
            authorization="suppressed" if blocked else "sent",
            outcome_status=None,
            checkout_status=None,
            evidence=evidence,
            protected_reference=self.protector.protect("request", request_id)[:20],
        )
        return {
            "device_id": device_id,
            "request_id": request_id,
            "operations": projection,
            "follow_ups": follow_ups,
            "timestamp": precheck_timestamp,
        }

    async def _emit_follow_up(
        self, anchor: datetime, offset: int, payload: dict, next_sequence
    ) -> str:
        """Send one already-scheduled outcome/checkout at its virtual time."""
        timestamp = anchor + timedelta(seconds=offset)
        namespace = payload["namespace"]
        if payload["kind"] == "outcome":
            await self.service.outcome(
                OutcomeRequest(
                    event_id=f"{namespace}_outcome_{payload['attempt']}",
                    request_id=payload["request_id"],
                    device_id=payload["device_id"],
                    session_id=payload["session_id"],
                    timestamp=timestamp,
                    event_sequence=next_sequence(),
                    authorization_result=payload["authorization_result"],
                    failure_reason=payload["failure_reason"],
                    payment_method="card",
                    card_last4=payload["card_last4"],
                    card_network=payload["card_network"],
                )
            )
            return payload["authorization_result"]
        await self.service.checkout(
            CheckoutRequest(
                event_id=f"{namespace}_checkout_{payload['attempt']}",
                request_id=payload["request_id"],
                device_id=payload["device_id"],
                session_id=payload["session_id"],
                timestamp=timestamp,
                event_sequence=next_sequence(),
            )
        )
        return "completed"

    # ------------------------------------------------------------------
    # Replay Lab: one device, one scenario, stepped manually
    # ------------------------------------------------------------------

    def start(self, scenario: str) -> dict:
        run_id = f"demo_{uuid.uuid4().hex[:12]}"
        run = DemoRun(run_id=run_id, scenario=scenario, anchor=self._clock_anchor())
        self.runs[run_id] = run
        return {
            "demo_id": run_id,
            "scenario": scenario,
            "total_attempts": len(SCENARIO_PLANS[scenario]),
            "position": 0,
        }

    async def step(self, demo_id: str) -> dict:
        run = self.runs.get(demo_id)
        if run is None:
            raise KeyError("demo session not found")
        plan = SCENARIO_PLANS[run.scenario]
        if run.index >= len(plan):
            return {"demo_id": demo_id, "complete": True, "position": run.index}

        spec = plan[run.index]
        attempt = run.index + 1
        run.elapsed_seconds += spec.gap_seconds

        def next_sequence() -> int:
            value = run.sequence
            run.sequence += 1
            return value

        result = await self._drive_attempt(
            namespace=run.run_id,
            device_key=run.run_id,
            anchor=run.anchor,
            offset_seconds=run.elapsed_seconds,
            attempt=attempt,
            spec=spec,
            next_sequence=next_sequence,
            checkout_already_sent=run.checkout_sent,
        )

        # The Replay Lab is a single device stepped one attempt at a time, so
        # its follow-ups can be flushed immediately: nothing else is competing
        # for the global clock between this attempt and the next one.
        outcome_status: str | None = None
        checkout_status: str | None = None
        for offset, payload in result["follow_ups"]:
            status = await self._emit_follow_up(
                run.anchor, offset, payload, next_sequence
            )
            if payload["kind"] == "outcome":
                outcome_status = status
            else:
                checkout_status = status
                run.checkout_sent = True

        projection = dict(result["operations"])
        projection["outcome_status"] = outcome_status
        projection["checkout_status"] = checkout_status

        run.index = attempt
        return {
            "demo_id": demo_id,
            "scenario": run.scenario,
            "complete": attempt >= len(plan),
            "position": attempt,
            "total_attempts": len(plan),
            "attempt": {
                "attempt": attempt,
                "amount": spec.amount,
                "currency": _DEMO_CURRENCY,
                "campaign_active": spec.campaign_active,
                "timestamp": result["timestamp"].isoformat(),
                "elapsed_seconds": run.elapsed_seconds,
            },
            "operations": projection,
            "timeline": self.service.timeline(result["device_id"]),
        }

    # ------------------------------------------------------------------
    # Live Traffic: many devices, one virtual clock
    # ------------------------------------------------------------------

    def start_traffic(self, seed: int | None = None) -> dict:
        """Begin a run. Without a seed one is drawn, so consecutive runs
        differ; with a seed the run is reproduced exactly."""
        run_id = f"traffic_{uuid.uuid4().hex[:12]}"
        resolved_seed = new_seed() if seed is None else int(seed)
        devices, schedule = schedule_for(resolved_seed)
        run = TrafficRun(
            run_id=run_id,
            seed=resolved_seed,
            anchor=self._clock_anchor(),
            schedule=schedule,
            devices={
                device.key: TrafficDeviceState(device=device) for device in devices
            },
        )
        self.traffic_runs[run_id] = run
        return {
            "traffic_run_id": run_id,
            "seed": resolved_seed,
            "total_payments": len(schedule),
            "device_count": len(devices),
            "position": 0,
            "run_totals": {"payments": 0, **run.counts},
            "clock": "compressed virtual simulation time",
        }

    async def step_traffic(self, traffic_run_id: str) -> dict:
        run = self.traffic_runs.get(traffic_run_id)
        if run is None:
            raise KeyError("traffic run not found")

        def next_sequence() -> int:
            value = run.sequence
            run.sequence += 1
            return value

        if run.index >= len(run.schedule):
            lifecycle_updates = await self._flush_pending(run, None, next_sequence)
            return {
                "traffic_run_id": traffic_run_id,
                "complete": True,
                "position": run.index,
                "total_payments": len(run.schedule),
                "run_totals": {"payments": run.index, **run.counts},
                "lifecycle_updates": lifecycle_updates,
            }

        scheduled = run.schedule[run.index]
        # Everything already due on the virtual clock must land before this
        # attempt, or the global (timestamp, event_sequence) order regresses
        # and the service rejects it as a late event.
        lifecycle_updates = await self._flush_pending(
            run, scheduled.offset_seconds, next_sequence
        )

        state = run.devices[scheduled.device.key]
        result = await self._drive_attempt(
            namespace=f"{run.run_id}_{scheduled.device.key}",
            device_key=scheduled.device.key,
            anchor=run.anchor,
            offset_seconds=scheduled.offset_seconds,
            attempt=scheduled.attempt,
            spec=scheduled.spec,
            next_sequence=next_sequence,
            checkout_already_sent=state.checkout_sent,
        )
        for offset, payload in result["follow_ups"]:
            if payload["kind"] == "checkout":
                state.checkout_sent = True
            run.pending.append((offset, run.pending_seq, payload))
            run.pending_seq += 1
        run.pending.sort(key=lambda row: (row[0], row[1]))

        projection = result["operations"]
        run.counts[projection["decision"]] += 1
        run.index += 1

        row = {
            "sequence": run.index,
            "device_key": scheduled.device.key,
            "attempt": scheduled.attempt,
            "amount": scheduled.spec.amount,
            "currency": _DEMO_CURRENCY,
            "campaign_active": scheduled.spec.campaign_active,
            "virtual_timestamp": result["timestamp"].isoformat(),
            "virtual_offset_seconds": scheduled.offset_seconds,
            "operations": projection,
        }
        state.attempts.append(row)
        return {
            "traffic_run_id": traffic_run_id,
            "complete": run.index >= len(run.schedule),
            "position": run.index,
            "total_payments": len(run.schedule),
            "run_totals": {"payments": run.index, **run.counts},
            "lifecycle_updates": lifecycle_updates,
            "payment": row,
        }

    async def _flush_pending(
        self, run: TrafficRun, boundary: int | None, next_sequence
    ) -> list[dict]:
        """Emit every queued follow-up due at or before `boundary`.

        `boundary=None` drains the queue (end of run). The pending list is
        kept sorted by (offset, insertion order), so this preserves globally
        non-decreasing virtual time.

        Returns the lifecycle updates that just landed, so already-displayed
        feed rows can move from "awaiting processor outcome" to the real
        result. That transition *is* the causal separation made visible: the
        decision was made at the earlier offset, the outcome only exists now.
        """
        applied: list[dict] = []
        while run.pending:
            offset, _order, payload = run.pending[0]
            if boundary is not None and offset > boundary:
                break
            run.pending.pop(0)
            status = await self._emit_follow_up(
                run.anchor, offset, payload, next_sequence
            )
            update = {
                "device_key": payload["device_key"],
                "attempt": payload["attempt"],
                "kind": payload["kind"],
                "status": status,
            }
            applied.append(update)
            self._apply_lifecycle_update(run, update)
        return applied

    @staticmethod
    def _apply_lifecycle_update(run: TrafficRun, update: dict) -> None:
        state = run.devices.get(update["device_key"])
        if state is None:
            return
        for row in state.attempts:
            if row["attempt"] != update["attempt"]:
                continue
            key = "outcome_status" if update["kind"] == "outcome" else "checkout_status"
            row["operations"][key] = update["status"]
            return

    def traffic_truth(self, traffic_run_id: str) -> dict:
        """Attribute already-made decisions to the scenarios that produced
        them. Called only on explicit operator request, strictly after the
        decisions exist. Nothing here feeds back into scoring."""
        run = self.traffic_runs.get(traffic_run_id)
        if run is None:
            raise KeyError("traffic run not found")
        devices = []
        for key, state in sorted(run.devices.items()):
            actions = [row["operations"]["decision"] for row in state.attempts]
            first_review = next(
                (
                    row["attempt"]
                    for row in state.attempts
                    if row["operations"]["decision"] in ("review", "block")
                ),
                None,
            )
            first_block = next(
                (
                    row["attempt"]
                    for row in state.attempts
                    if row["operations"]["decision"] == "block"
                ),
                None,
            )
            intervention = next(
                (
                    row["virtual_offset_seconds"] - state.device.start_offset_seconds
                    for row in state.attempts
                    if row["operations"]["decision"] in ("review", "block")
                ),
                None,
            )
            devices.append(
                {
                    "device_key": key,
                    "scenario": state.device.scenario,
                    "scenario_label": SCENARIO_CATALOG[state.device.scenario]["label"],
                    "is_attack": state.device.scenario.endswith("_attacker"),
                    "payments_scored": len(state.attempts),
                    "actions": actions,
                    "first_review_attempt": first_review,
                    "first_block_attempt": first_block,
                    "virtual_seconds_to_first_intervention": intervention,
                    "detected": first_review is not None,
                }
            )
        return {
            "traffic_run_id": traffic_run_id,
            "seed": run.seed,
            "devices": devices,
            "disclosure": (
                "Ground truth is held only by the simulator and was attached "
                "after every decision above was already made. It is never a "
                "field of PrecheckRequest and never reaches features, the "
                "model or the policy."
            ),
        }

    def reset(self) -> dict:
        """Clear this manager's in-memory run cursors only. The shared
        SQLite repository -- and every request/event any run has ever
        written to it -- is never touched here."""
        self.runs.clear()
        self.traffic_runs.clear()
        return {"reset": True}
