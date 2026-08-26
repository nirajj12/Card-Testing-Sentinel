"""Demo orchestration driving the real production FraudDetectionService.

This intentionally does not construct a second scoring path, a second
feature engine, a second policy, or a second (in-memory) repository. It is
handed the *same* FraudDetectionService instance -- backed by the same
SQLite repository -- that live `/api/precheck` traffic uses, and drives it
through real precheck/outcome/checkout transitions with uniquely
namespaced synthetic identifiers per run. That is the safer of the two
designs considered for Stage 4 (see the Stage 3-4 checkpoint report): the
alternative -- the frontend calling the lifecycle endpoints directly with
client-picked identifiers -- would need the browser to independently
reconstruct a demo clock anchor and per-run namespace, duplicating logic
that is otherwise only ever in one place here.

`reset()` only clears this manager's in-memory run bookkeeping (the
`self.runs` cursor). It never touches the shared repository, so it can
never erase persisted audit history.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from card_testing_sentinel.api.contracts import (
    CheckoutRequest,
    OutcomeRequest,
    PrecheckRequest,
)
from card_testing_sentinel.security.identifiers import IdentifierProtector
from card_testing_sentinel.services.fraud_detection import FraudDetectionService
from card_testing_sentinel.services.operations_projection import build_projection
from card_testing_sentinel.services.scenario_generation import (
    SCENARIO_CATALOG,
    SCENARIO_PLANS,
)

_OUTCOME_LAG_SECONDS = 1
_CHECKOUT_LAG_SECONDS = 30
_DEMO_CURRENCY = "INR"
_DEMO_CARD_BIN = "410000"


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


class DemoManager:
    def __init__(self, service: FraudDetectionService, protector: IdentifierProtector):
        self.service = service
        self.protector = protector
        self.runs: dict[str, DemoRun] = {}

    def scenarios(self) -> list[dict]:
        return [
            {"id": name, "label": spec["label"], "attempts": spec["attempts"]}
            for name, spec in SCENARIO_CATALOG.items()
        ]

    def _clock_anchor(self) -> datetime:
        """The demo clock must begin strictly after the latest persisted
        (timestamp, event_sequence) in the shared repository -- global
        ordering, the same tuple `FraudDetectionService._assert_not_late`
        compares against -- so any future-dated row already committed
        (from a previous demo run, or live traffic) can never make a fresh
        run's first attempt look late. With no persisted rows yet, the
        current wall-clock time is used instead; there is nothing to be
        strictly after."""
        latest = self.service.repository.latest_order()
        if latest is None:
            return datetime.now(UTC)
        latest_timestamp = datetime.fromisoformat(latest[0])
        return latest_timestamp + timedelta(seconds=1)

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

        # Every identifier below is namespaced under this run's unique
        # `run_id` -- a fresh run never collides with, or mutates, any
        # other run's or any live request's audit history, and the
        # scenario label itself never appears in any of these values.
        device_id = f"{run.run_id}_device"
        session_id = f"{run.run_id}_{spec.session_suffix}"
        card_reference = f"{run.run_id}_{spec.card_suffix}"
        ip_reference = f"{run.run_id}_{spec.ip_suffix}"
        request_id = f"{run.run_id}_request_{attempt}"

        run.elapsed_seconds += spec.gap_seconds
        precheck_timestamp = run.anchor + timedelta(seconds=run.elapsed_seconds)
        precheck_request = PrecheckRequest(
            request_id=request_id,
            event_id=f"{run.run_id}_precheck_{attempt}",
            device_id=device_id,
            session_id=session_id,
            card_reference=card_reference,
            card_bin=_DEMO_CARD_BIN,
            ip_reference=ip_reference,
            amount=spec.amount,
            currency=_DEMO_CURRENCY,
            timestamp=precheck_timestamp,
            event_sequence=run.sequence,
            campaign_active=spec.campaign_active,
        )
        run.sequence += 1
        response, evidence = await self.service.precheck_with_evidence(precheck_request)

        outcome_status: str | None = None
        checkout_status: str | None = None
        blocked = response.decision == "block"
        authorization = "suppressed" if blocked else "sent"

        if not blocked:
            outcome_timestamp = precheck_timestamp + timedelta(
                seconds=_OUTCOME_LAG_SECONDS
            )
            outcome_request = OutcomeRequest(
                event_id=f"{run.run_id}_outcome_{attempt}",
                request_id=request_id,
                device_id=device_id,
                session_id=session_id,
                timestamp=outcome_timestamp,
                event_sequence=run.sequence,
                authorization_result=spec.authorization_result,
                decline_reason=spec.decline_reason,
            )
            run.sequence += 1
            await self.service.outcome(outcome_request)
            outcome_status = spec.authorization_result

            if spec.authorization_result == "approved" and not run.checkout_sent:
                checkout_timestamp = outcome_timestamp + timedelta(
                    seconds=_CHECKOUT_LAG_SECONDS
                )
                checkout_request = CheckoutRequest(
                    event_id=f"{run.run_id}_checkout_{attempt}",
                    request_id=request_id,
                    device_id=device_id,
                    session_id=session_id,
                    timestamp=checkout_timestamp,
                    event_sequence=run.sequence,
                )
                run.sequence += 1
                await self.service.checkout(checkout_request)
                run.checkout_sent = True
                checkout_status = "completed"

        run.index = attempt

        protected_reference = self.protector.protect("request", request_id)[:20]
        projection = build_projection(
            decision=response.decision,
            risk_score=response.risk_score,
            rule_score=response.rule_score,
            reason_codes=response.reason_codes,
            state_version=response.device_state_version,
            latency_ms=response.latency_ms,
            idempotent_replay=response.idempotent_replay,
            authorization=authorization,
            outcome_status=outcome_status,
            checkout_status=checkout_status,
            evidence=evidence,
            protected_reference=protected_reference,
        )

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
                "card_alias": f"Synthetic {spec.card_suffix.replace('_', ' ').title()}",
                "timestamp": precheck_timestamp.isoformat(),
                "elapsed_seconds": run.elapsed_seconds,
            },
            "operations": projection,
            "timeline": self.service.timeline(device_id),
        }

    def reset(self) -> dict:
        """Clear this manager's in-memory run cursor only. The shared
        SQLite repository -- and every request/event any run has ever
        written to it -- is never touched here."""
        self.runs.clear()
        return {"reset": True}
