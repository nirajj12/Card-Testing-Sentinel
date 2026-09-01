"""Causal guarantees of the merchant-side runtime core.

For attempt N the snapshot may use attempts 1..N-1 only -- never the
current attempt's outcome, card metadata, or the future checkout result.
Ordering is enforced per device, so independent devices never block each
other.
"""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from card_testing_sentinel.api.contracts import (
    CheckoutRequest,
    OutcomeRequest,
    PrecheckRequest,
)
from card_testing_sentinel.domain.exceptions import (
    CausalOrderingError,
    DuplicateConflictError,
    InvalidLifecycleTransition,
)
from card_testing_sentinel.persistence.memory_repository import InMemoryStateRepository
from card_testing_sentinel.security.identifiers import IdentifierProtector
from card_testing_sentinel.services.risk_service import RiskService

START = datetime(2031, 1, 1, tzinfo=UTC)


class RecordingModel:
    """Stands in for the trained model so these tests stay about causality,
    not about any particular model's numbers. It records every snapshot it is
    asked to score and returns a fixed low score."""

    status = "ready"

    def __init__(self, score: float = 0.05):
        self.snapshots = []
        self._score = score

    def score(self, snapshot):
        self.snapshots.append(dict(snapshot))
        return self._score


def _service(registry, score: float = 0.05):
    model = RecordingModel(score)
    view = type(
        "RegistryView",
        (),
        {
            "model": model,
            "policy": registry.policy,
            "policy_mode": "model_and_rules",
        },
    )()
    service = RiskService(
        view,
        InMemoryStateRepository(),
        IdentifierProtector.from_secret("causal-test-secret-0123456789"),
    )
    return service, model


def _precheck(index, when, *, device="device-a", session=None, ip="198.51.100.1"):
    return PrecheckRequest(
        request_id=f"r{index}",
        event_id=f"q{index}",
        merchant_id="merchant-x",
        device_id=device,
        session_id=session or f"s-{device}",
        ip_reference=ip,
        amount=2.0,
        currency="USD",
        campaign_active=False,
        timestamp=when,
        event_sequence=index * 10,
    )


def _outcome(index, when, *, device="device-a", approved=False, card_last4=None):
    return OutcomeRequest(
        event_id=f"o{index}",
        request_id=f"r{index}",
        device_id=device,
        session_id=f"s-{device}",
        timestamp=when,
        event_sequence=index * 10 + 1,
        authorization_result="approved" if approved else "declined",
        failure_reason=None if approved else "generic_decline",
        payment_method="card" if card_last4 else None,
        card_last4=card_last4,
        card_network="visa" if card_last4 else None,
    )


def test_current_outcome_is_absent_and_a_prior_decline_only_affects_later(registry):
    service, model = _service(registry)
    asyncio.run(service.precheck(_precheck(1, START)))
    assert model.snapshots[0]["decline_streak"] == 0
    assert model.snapshots[0]["recent_failures_24h"] == 0

    asyncio.run(service.outcome(_outcome(1, START + timedelta(seconds=1))))
    asyncio.run(service.precheck(_precheck(3, START + timedelta(seconds=10))))
    assert model.snapshots[1]["decline_streak"] == 1
    assert model.snapshots[1]["recent_failures_24h"] == 1


def test_historical_card_metadata_only_reaches_a_later_attempt(registry):
    service, model = _service(registry)
    asyncio.run(service.precheck(_precheck(1, START)))
    # attempt 1's snapshot cannot know any card -- none exists yet
    assert model.snapshots[0]["distinct_card_last4_7d"] == 0

    asyncio.run(
        service.outcome(_outcome(1, START + timedelta(seconds=1), card_last4="4111"))
    )
    asyncio.run(service.precheck(_precheck(3, START + timedelta(seconds=20))))
    # attempt 3 may use the verified card from attempt 1's outcome
    assert model.snapshots[1]["distinct_card_last4_7d"] == 1


def test_checkout_result_only_affects_a_future_request(registry):
    service, model = _service(registry)
    asyncio.run(service.precheck(_precheck(1, START)))
    asyncio.run(
        service.outcome(_outcome(1, START + timedelta(seconds=1), approved=True))
    )
    checkout = CheckoutRequest(
        event_id="c1",
        request_id="r1",
        device_id="device-a",
        session_id="s-device-a",
        timestamp=START + timedelta(seconds=2),
        event_sequence=12,
    )
    asyncio.run(service.checkout(checkout))
    assert asyncio.run(service.checkout(checkout)).idempotent_replay is True

    asyncio.run(service.precheck(_precheck(4, START + timedelta(seconds=30))))
    assert model.snapshots[0]["successful_checkouts"] == 0
    assert model.snapshots[1]["successful_checkouts"] == 1


def test_blocked_request_cannot_receive_an_outcome_but_later_requests_still_score(
    registry,
):
    # A block is now driven by the model score plus corroborating evidence,
    # so the stub scores high; the burst supplies the evidence.
    service, model = _service(registry, score=0.99)
    decisions = []
    for i in range(1, 11):
        when = START + timedelta(seconds=i * 3)
        decisions.append(
            asyncio.run(
                service.precheck(
                    _precheck(i, when, device="burst", session=f"s-burst-{i // 3}")
                )
            )
        )
    assert any(d.decision == "block" for d in decisions)
    blocked = next(i for i, d in enumerate(decisions, 1) if d.decision == "block")
    with pytest.raises(InvalidLifecycleTransition, match="blocked request"):
        asyncio.run(
            service.outcome(
                _outcome(
                    blocked,
                    START + timedelta(seconds=blocked * 3 + 1),
                    device="burst",
                ).model_copy(update={"session_id": f"s-burst-{blocked // 3}"})
            )
        )
    # a later request from the same device is still scored
    later = asyncio.run(
        service.precheck(_precheck(99, START + timedelta(seconds=400), device="burst"))
    )
    assert later.decision in {"allow", "review", "block"}
    assert later.risk_score == pytest.approx(0.99)
    assert later.model_status == "ready"


def test_independent_devices_do_not_block_each_other_on_interleaved_timestamps(
    registry,
):
    service, model = _service(registry)
    # device A commits an event at t+100
    asyncio.run(
        service.precheck(_precheck(1, START + timedelta(seconds=100), device="A"))
    )
    # device B then commits an EARLIER timestamp -- must be accepted
    ok = asyncio.run(
        service.precheck(_precheck(2, START + timedelta(seconds=10), device="B"))
    )
    assert ok.decision in {"allow", "review", "block"}
    # but device B going backwards against ITS OWN last event is rejected
    with pytest.raises(CausalOrderingError):
        asyncio.run(
            service.precheck(_precheck(3, START + timedelta(seconds=5), device="B"))
        )


def test_exact_replay_and_conflicting_retry(registry):
    service, model = _service(registry)
    request = _precheck(1, START)
    first = asyncio.run(service.precheck(request))
    calls = len(model.snapshots)
    replay = asyncio.run(service.precheck(request))
    assert replay.idempotent_replay is True
    assert replay.decision == first.decision
    assert replay.device_state_version == first.device_state_version
    assert len(model.snapshots) == calls  # no rescoring on replay

    with pytest.raises(DuplicateConflictError):
        asyncio.run(service.precheck(request.model_copy(update={"amount": 9.0})))


def test_duplicate_outcome_is_idempotent(registry):
    service, _ = _service(registry)
    asyncio.run(service.precheck(_precheck(1, START)))
    outcome = _outcome(1, START + timedelta(seconds=1))
    first = asyncio.run(service.outcome(outcome))
    again = asyncio.run(service.outcome(outcome))
    assert again.idempotent_replay is True
    assert again.device_state_version == first.device_state_version
