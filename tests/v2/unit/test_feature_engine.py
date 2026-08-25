from datetime import UTC, datetime, timedelta

import pytest

from card_testing_sentinel.v2.data.contracts import (
    ConflictingDuplicateError,
    EventContractError,
    LateEventError,
    LifecycleEvent,
)
from card_testing_sentinel.v2.features.engine import CausalFeatureEngine, _within
from card_testing_sentinel.v2.features.state import ProcessedAuthorization

BASE = datetime(2026, 1, 1, tzinfo=UTC)


def request(
    number, *, seconds=0, card="card_1", session="session_1", ip="ip_1", amount=10.0
):
    return LifecycleEvent(
        event_id=f"event_request_{number}",
        request_id=f"request_{number}",
        event_sequence=number * 2,
        timestamp=BASE + timedelta(seconds=seconds),
        event_type="authorization_request",
        device_id="device_1",
        session_id=session,
        ip_fingerprint=ip,
        card_fingerprint=card,
        card_bin="410001",
        amount=amount,
        currency="USD",
        campaign_active=False,
    )


def outcome(number, result, *, seconds):
    return LifecycleEvent(
        event_id=f"event_outcome_{number}",
        request_id=f"request_{number}",
        event_sequence=number * 2 + 1,
        timestamp=BASE + timedelta(seconds=seconds),
        event_type="authorization_outcome",
        device_id="device_1",
        session_id="session_1",
        authorization_result=result,
        decline_reason="generic_decline" if result == "declined" else None,
    )


def test_manual_causal_features_and_outcome_visibility():
    engine = CausalFeatureEngine()
    first = engine.precheck(request(1, amount=10))
    engine.record_outcome(outcome(1, "declined", seconds=1))
    second = engine.precheck(request(2, seconds=10, card="card_2", amount=12))
    assert first["prior_attempts_10s"] == 0
    assert first["prospective_requests_10s"] == 1
    assert first["distinct_cards_5m"] == 1
    assert first["prior_decline_streak"] == 0
    assert second["prior_attempts_10s"] == 1
    assert second["prior_attempts_60s"] == 1
    assert second["prior_attempts_5m"] == 1
    assert second["prospective_requests_10s"] == 2
    assert second["distinct_cards_5m"] == 2
    assert second["distinct_bins_5m"] == 1
    assert second["prior_decline_streak"] == 1
    assert second["prior_decline_ratio_5m"] == 1
    assert second["attempts_before_first_approval"] == 1
    assert second["attempts_after_first_approval"] == 0
    assert second["seconds_since_previous_authorization"] == 10
    assert second["device_age_seconds"] == 10
    assert second["session_age_seconds"] == 10
    assert second["same_card_retry_ratio_24h"] == 0
    assert second["amount_delta_from_previous"] == 2
    assert second["current_amount"] == 12


def test_idempotency_conflict_block_and_late_event_behavior():
    engine = CausalFeatureEngine()
    event = request(1)
    assert engine.precheck(event) == engine.precheck(event)
    conflict = event.model_copy(update={"amount": 11.0})
    with pytest.raises(ConflictingDuplicateError):
        engine.precheck(conflict)
    blocked = request(2, seconds=5)
    engine.precheck(blocked, blocked=True)
    with pytest.raises(EventContractError, match="blocked"):
        engine.record_outcome(outcome(2, "approved", seconds=6))
    late = request(3, seconds=1)
    with pytest.raises(LateEventError):
        engine.precheck(late)


def test_completion_is_causal_and_emits_no_score():
    engine = CausalFeatureEngine()
    engine.precheck(request(1))
    engine.record_outcome(outcome(1, "approved", seconds=1))
    completion = LifecycleEvent(
        event_id="completion_1",
        request_id="request_1",
        event_sequence=4,
        timestamp=BASE + timedelta(seconds=3),
        event_type="checkout_completion",
        device_id="device_1",
        session_id="session_1",
    )
    assert engine.record_completion(completion) is None
    later = engine.precheck(request(3, seconds=5))
    assert later["prior_successful_checkouts"] == 1
    assert later["seconds_since_successful_checkout"] == 2


def test_window_boundary_is_inclusive_and_timestamp_ties_use_sequence():
    engine = CausalFeatureEngine()
    engine.precheck(request(1))
    engine.record_outcome(outcome(1, "declined", seconds=1))
    at_boundary = engine.precheck(request(2, seconds=10))
    assert at_boundary["prior_attempts_10s"] == 1
    tied = request(3, seconds=10, card="card_3")
    tied = tied.model_copy(update={"event_sequence": 6})
    assert engine.precheck(tied)["prospective_requests_10s"] == 3
    after_boundary = request(4, seconds=10.001)
    assert engine.precheck(after_boundary)["prior_attempts_10s"] == 0


@pytest.mark.parametrize(
    "window",
    [
        timedelta(seconds=10),
        timedelta(seconds=60),
        timedelta(minutes=5),
        timedelta(hours=1),
        timedelta(hours=24),
        timedelta(days=7),
    ],
)
def test_all_window_lower_boundaries_are_closed_and_upper_bound_is_open(window):
    def record(timestamp):
        return ProcessedAuthorization(
            request_id=str(timestamp),
            timestamp=timestamp,
            session_id="session",
            ip_fingerprint="ip",
            card_fingerprint="card",
            card_bin="410001",
            amount=10,
            approved=False,
        )

    epsilon = timedelta(microseconds=1)
    records = [
        record(BASE - window - epsilon),
        record(BASE - window),
        record(BASE - window + epsilon),
        record(BASE),
    ]
    included = _within(records, BASE, window)
    assert [item.timestamp for item in included] == [
        BASE - window,
        BASE - window + epsilon,
    ]
