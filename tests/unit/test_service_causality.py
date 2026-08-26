import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

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
from card_testing_sentinel.persistence.memory_repository import (
    InMemoryStateRepository,
)
from card_testing_sentinel.security.identifiers import IdentifierProtector
from card_testing_sentinel.services.fraud_detection import FraudDetectionService


class CapturingScorer:
    def __init__(self, risk=0.01):
        self.risk = risk
        self.snapshots = []

    def score_snapshot(self, snapshot):
        self.snapshots.append(dict(snapshot))
        return self.risk, self.risk


def _service(registry, risk=0.01, repository=None):
    scorer = CapturingScorer(risk)
    local_registry = SimpleNamespace(
        scorer=scorer,
        policy=registry.policy,
        model_version=registry.model_version,
        policy_version=registry.policy_version,
    )
    service = FraudDetectionService(
        local_registry,
        repository or InMemoryStateRepository(),
        IdentifierProtector.from_secret("causal-test-secret-0123456789"),
    )
    return service, scorer


def _precheck(index, timestamp, *, device="device", card=None, ip="198.51.100.1"):
    return PrecheckRequest(
        request_id=f"r{index}",
        event_id=f"q{index}",
        device_id=device,
        session_id=f"session-{device}",
        card_reference=card or f"card-{index}",
        card_bin="410000",
        ip_reference=ip,
        amount=2.0,
        currency="USD",
        timestamp=timestamp,
        event_sequence=index * 3,
        campaign_active=False,
    )


def _outcome(index, timestamp, *, device="device", approved=False):
    return OutcomeRequest(
        event_id=f"o{index}",
        request_id=f"r{index}",
        device_id=device,
        session_id=f"session-{device}",
        timestamp=timestamp,
        event_sequence=index * 3 + 1,
        authorization_result="approved" if approved else "declined",
        decline_reason=None if approved else "generic_decline",
    )


def test_current_outcome_absent_and_allowed_outcome_only_affects_later(registry):
    service, scorer = _service(registry)
    start = datetime(2031, 1, 1, tzinfo=UTC)
    asyncio.run(service.precheck(_precheck(1, start)))
    assert scorer.snapshots[0]["prior_decline_streak"] == 0
    asyncio.run(service.outcome(_outcome(1, start + timedelta(seconds=1))))
    asyncio.run(service.precheck(_precheck(2, start + timedelta(seconds=10))))
    assert scorer.snapshots[1]["prior_decline_streak"] == 1


def test_block_suppresses_current_outcome_but_later_request_scored(registry):
    service, scorer = _service(registry, risk=0.95)
    start = datetime(2031, 1, 1, tzinfo=UTC)
    decisions = []
    for index in range(1, 5):
        request_time = start + timedelta(seconds=index * 10)
        decisions.append(asyncio.run(service.precheck(_precheck(index, request_time))))
        if decisions[-1].decision != "block":
            asyncio.run(
                service.outcome(_outcome(index, request_time + timedelta(seconds=1)))
            )
    assert decisions[3].decision == "block"
    with pytest.raises(InvalidLifecycleTransition, match="blocked request"):
        asyncio.run(service.outcome(_outcome(4, start + timedelta(seconds=41))))
    fifth = asyncio.run(service.precheck(_precheck(5, start + timedelta(seconds=50))))
    assert fifth.decision in {"allow", "review", "block"}
    assert len(scorer.snapshots) == 5
    assert scorer.snapshots[4]["prospective_requests_60s"] == 5


def test_checkout_affects_only_future_request(registry):
    service, scorer = _service(registry)
    start = datetime(2031, 1, 1, tzinfo=UTC)
    asyncio.run(service.precheck(_precheck(1, start)))
    asyncio.run(
        service.outcome(_outcome(1, start + timedelta(seconds=1), approved=True))
    )
    checkout = CheckoutRequest(
        event_id="c1",
        request_id="r1",
        device_id="device",
        session_id="session-device",
        timestamp=start + timedelta(seconds=2),
        event_sequence=5,
    )
    asyncio.run(service.checkout(checkout))
    retry = asyncio.run(service.checkout(checkout))
    assert retry.idempotent_replay is True
    asyncio.run(service.precheck(_precheck(2, start + timedelta(seconds=10))))
    assert scorer.snapshots[0]["prior_successful_checkouts"] == 0
    assert scorer.snapshots[1]["prior_successful_checkouts"] == 1
    assert scorer.snapshots[1]["checkout_completion_lag_available"] == 1


def test_shared_ip_and_timestamp_ties_are_causal(registry):
    service, scorer = _service(registry)
    when = datetime(2031, 1, 1, tzinfo=UTC)
    first = _precheck(1, when, device="a", ip="shared-network")
    second = _precheck(2, when, device="b", ip="shared-network").model_copy(
        update={"event_sequence": first.event_sequence + 1}
    )
    asyncio.run(service.precheck(first))
    asyncio.run(service.precheck(second))
    assert scorer.snapshots[0]["requests_per_ip_5m"] == 1
    assert scorer.snapshots[1]["requests_per_ip_5m"] == 2
    late = _precheck(3, when, device="c").model_copy(update={"event_sequence": 1})
    with pytest.raises(CausalOrderingError):
        asyncio.run(service.precheck(late))


def test_concurrent_identical_conflicting_and_same_device_requests(registry):
    service, _scorer = _service(registry)
    start = datetime(2031, 1, 1, tzinfo=UTC)
    request = _precheck(1, start)

    async def identical():
        return await asyncio.gather(
            service.precheck(request), service.precheck(request)
        )

    results = asyncio.run(identical())
    assert {row.idempotent_replay for row in results} == {False, True}
    assert results[0].device_state_version == results[1].device_state_version

    conflicting = request.model_copy(update={"amount": 3.0})
    with pytest.raises(DuplicateConflictError):
        asyncio.run(service.precheck(conflicting))

    second = _precheck(2, start + timedelta(seconds=10))
    third = _precheck(3, start + timedelta(seconds=20))

    async def ordered():
        return await asyncio.gather(service.precheck(second), service.precheck(third))

    later = asyncio.run(ordered())
    assert [row.device_state_version for row in later] == [2, 3]
