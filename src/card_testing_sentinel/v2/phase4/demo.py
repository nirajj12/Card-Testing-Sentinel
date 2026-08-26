"""Separate in-memory raw-event scenarios for the local dashboard demo."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from card_testing_sentinel.v2.phase4.artifact_registry import ArtifactRegistry
from card_testing_sentinel.v2.phase4.contracts import (
    CheckoutRequest,
    OutcomeRequest,
    PrecheckRequest,
)
from card_testing_sentinel.v2.phase4.security import IdentifierProtector
from card_testing_sentinel.v2.phase4.service import LiveScoringService
from card_testing_sentinel.v2.phase4.state.memory_repository import (
    InMemoryStateRepository,
)

SCENARIOS = {
    "normal_customer": {
        "label": "Normal customer",
        "attempts": 3,
        "gap": 90,
        "cards": 1,
    },
    "normal_bad_luck": {
        "label": "Normal bad luck",
        "attempts": 6,
        "gap": 55,
        "cards": 2,
    },
    "flash_standard": {"label": "Flash standard", "attempts": 4, "gap": 35, "cards": 1},
    "flash_hard_retry": {
        "label": "Flash hard retry",
        "attempts": 7,
        "gap": 25,
        "cards": 1,
    },
    "burst_attacker": {"label": "Burst attacker", "attempts": 10, "gap": 4, "cards": 6},
    "evasive_attacker": {
        "label": "Evasive attacker",
        "attempts": 9,
        "gap": 90,
        "cards": 5,
    },
    "patient_attacker": {
        "label": "Patient attacker",
        "attempts": 9,
        "gap": 600,
        "cards": 5,
    },
}


class DemoManager:
    def __init__(self, registry: ArtifactRegistry, protector: IdentifierProtector):
        self.registry = registry
        self.protector = protector
        self.sessions: dict[str, dict] = {}

    def scenarios(self) -> list[dict]:
        return [
            {"id": name, "label": spec["label"], "attempts": spec["attempts"]}
            for name, spec in SCENARIOS.items()
        ]

    def start(self, scenario: str) -> dict:
        demo_id = f"demo_{uuid.uuid4().hex[:12]}"
        repository = InMemoryStateRepository()
        service = LiveScoringService(self.registry, repository, self.protector)
        self.sessions = {
            demo_id: {
                "scenario": scenario,
                "index": 0,
                "service": service,
                "started": datetime.now(UTC),
            }
        }
        return {
            "demo_id": demo_id,
            "scenario": scenario,
            "total_attempts": SCENARIOS[scenario]["attempts"],
            "position": 0,
        }

    async def step(self, demo_id: str) -> dict:
        session = self.sessions.get(demo_id)
        if session is None:
            raise KeyError("demo session not found")
        spec = SCENARIOS[session["scenario"]]
        index = session["index"]
        if index >= spec["attempts"]:
            return {"demo_id": demo_id, "complete": True, "position": index}
        attempt = index + 1
        timestamp = session["started"] + timedelta(seconds=attempt * spec["gap"])
        device = f"{demo_id}_device"
        request_id = f"{demo_id}_request_{attempt}"
        card = f"{demo_id}_card_{1 + (index % spec['cards'])}"
        campaign = session["scenario"].startswith("flash")
        request = PrecheckRequest(
            request_id=request_id,
            event_id=f"{demo_id}_precheck_{attempt}",
            device_id=device,
            session_id=f"{demo_id}_session_{1 + index // 4}",
            card_reference=card,
            card_bin="410000",
            ip_reference=f"demo-ip-{1 + index // 3}",
            amount=2.0 if "attacker" in session["scenario"] else 24.0,
            currency="USD",
            timestamp=timestamp,
            event_sequence=attempt * 3,
            campaign_active=campaign,
        )
        decision = await session["service"].precheck(request)
        outcome = None
        if decision.decision != "block":
            approved = (
                session["scenario"] in {"normal_customer", "flash_standard"}
                and attempt >= 2
            )
            outcome_request = OutcomeRequest(
                event_id=f"{demo_id}_outcome_{attempt}",
                request_id=request_id,
                device_id=device,
                session_id=request.session_id,
                timestamp=timestamp + timedelta(seconds=1),
                event_sequence=attempt * 3 + 1,
                authorization_result="approved" if approved else "declined",
                decline_reason=None if approved else "generic_decline",
            )
            outcome = (await session["service"].outcome(outcome_request)).model_dump(
                mode="json"
            )
            if approved and attempt == spec["attempts"]:
                checkout = CheckoutRequest(
                    event_id=f"{demo_id}_checkout_{attempt}",
                    request_id=request_id,
                    device_id=device,
                    session_id=request.session_id,
                    timestamp=timestamp + timedelta(seconds=30),
                    event_sequence=attempt * 3 + 2,
                )
                await session["service"].checkout(checkout)
        session["index"] = attempt
        return {
            "demo_id": demo_id,
            "complete": attempt >= spec["attempts"],
            "position": attempt,
            "total_attempts": spec["attempts"],
            "request": {
                "request_id": request_id,
                "amount": request.amount,
                "currency": request.currency,
                "attempt": attempt,
                "card_number": 1 + (index % spec["cards"]),
                "campaign_active": campaign,
            },
            "decision": decision.model_dump(mode="json"),
            "outcome": outcome,
            "timeline": session["service"].timeline(device),
        }

    def reset(self) -> dict:
        for session in self.sessions.values():
            session["service"].close()
        self.sessions.clear()
        return {"reset": True}
