from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from card_testing_sentinel.v2.data.contracts import (
    ConflictingDuplicateError,
    EventContractError,
    LateEventError,
    LifecycleEvent,
)
from card_testing_sentinel.v2.features.state import ProcessedAuthorization
from card_testing_sentinel.v2.phase2b.batch import replay_training_events
from card_testing_sentinel.v2.phase2b.engine import Phase2BFeatureEngine
from card_testing_sentinel.v2.phase2b.features import (
    MODEL_FEATURE_COLUMNS,
    NEW_FEATURES,
    validate_model_feature_contract,
)

NOW = datetime(2026, 8, 1, tzinfo=UTC)


def request(
    sequence: int,
    *,
    timestamp: datetime = NOW,
    device: str = "device-1",
    session: str = "session-1",
    ip: str = "ip-1",
    card: str = "card-1",
    amount: float = 10.0,
) -> LifecycleEvent:
    return LifecycleEvent(
        event_id=f"request-event-{sequence}-{device}",
        request_id=f"request-{sequence}-{device}",
        event_sequence=sequence,
        timestamp=timestamp,
        event_type="authorization_request",
        device_id=device,
        session_id=session,
        ip_fingerprint=ip,
        card_fingerprint=card,
        card_bin="411111",
        amount=amount,
        currency="USD",
        campaign_active=False,
    )


def outcome(
    sequence: int,
    *,
    request_sequence: int,
    timestamp: datetime,
    device: str = "device-1",
    session: str = "session-1",
    result: str = "approved",
) -> LifecycleEvent:
    return LifecycleEvent(
        event_id=f"outcome-event-{sequence}-{device}",
        request_id=f"request-{request_sequence}-{device}",
        event_sequence=sequence,
        timestamp=timestamp,
        event_type="authorization_outcome",
        device_id=device,
        session_id=session,
        authorization_result=result,
        decline_reason="declined" if result == "declined" else None,
    )


def completion(sequence: int, *, request_sequence: int, timestamp: datetime):
    return LifecycleEvent(
        event_id=f"completion-{sequence}",
        request_id=f"request-{request_sequence}-device-1",
        event_sequence=sequence,
        timestamp=timestamp,
        event_type="checkout_completion",
        device_id="device-1",
        session_id="session-1",
    )


def processed(timestamp: datetime, *, card="card-old", ip="ip-old", amount=10.0):
    return ProcessedAuthorization(
        request_id=str(timestamp),
        timestamp=timestamp,
        session_id="historical-session",
        ip_fingerprint=ip,
        card_fingerprint=card,
        card_bin="411111",
        amount=amount,
        approved=True,
    )


def test_feature_contract_is_explicit_unique_and_safe():
    validate_model_feature_contract()
    assert tuple(MODEL_FEATURE_COLUMNS[-len(NEW_FEATURES) :]) == NEW_FEATURES
    assert len(MODEL_FEATURE_COLUMNS) == 44


def test_empty_state_and_first_request_missing_history_contract():
    values = Phase2BFeatureEngine().precheck(request(1))
    assert values["prior_attempts_14d"] == 0
    assert values["distinct_cards_14d"] == 1
    assert values["amount_continuity_score_30d"] == 0
    assert values["amount_continuity_history_available"] == 0
    assert values["ip_rotation_ratio_24h"] == 1
    assert values["checkout_completion_lag_seconds"] == 0
    assert values["checkout_completion_lag_available"] == 0


def test_amount_continuity_same_slight_and_large_change():
    engine = Phase2BFeatureEngine()
    engine.devices["device-1"].processed.extend(
        [
            processed(NOW - timedelta(days=2), amount=9),
            processed(NOW - timedelta(days=1), amount=11),
        ]
    )
    same = engine._phase2b_snapshot(request(1, amount=10))
    slight = engine._phase2b_snapshot(request(2, amount=11))
    large = engine._phase2b_snapshot(request(3, amount=20))
    assert same["amount_continuity_score_30d"] == 0
    assert slight["amount_continuity_score_30d"] == 1
    assert large["amount_continuity_score_30d"] == 10
    assert large["amount_continuity_history_available"] == 1


def test_repeated_request_card_switch_and_same_card_retry():
    engine = Phase2BFeatureEngine()
    first = request(1, timestamp=NOW - timedelta(seconds=2), card="card-1")
    engine.precheck(first)
    engine.record_outcome(
        outcome(2, request_sequence=1, timestamp=NOW - timedelta(seconds=1))
    )
    same = engine._phase2b_snapshot(request(3, card="card-1"))
    switched = engine._phase2b_snapshot(request(4, card="card-2"))
    assert same["prior_attempts_14d"] == 1
    assert same["distinct_cards_14d"] == 1
    assert switched["distinct_cards_14d"] == 2


def test_multiple_sessions_and_ip_rotation_ratio_with_shared_ip():
    engine = Phase2BFeatureEngine()
    state = engine.devices["device-1"]
    state.processed.extend(
        [
            processed(NOW - timedelta(hours=2), ip="ip-1"),
            processed(NOW - timedelta(hours=1), ip="ip-2"),
        ]
    )
    engine.ip_history["ip-1"].append(
        (NOW - timedelta(hours=2), "device-1", "session-1")
    )
    engine.ip_history["ip-2"].extend(
        [
            (NOW - timedelta(hours=1), "device-1", "session-2"),
            (NOW - timedelta(minutes=30), "device-2", "session-x"),
        ]
    )
    values = engine._phase2b_snapshot(request(3, session="session-3", ip="ip-3"))
    assert values["ip_rotation_ratio_24h"] == 1.5


def test_prior_checkout_lag_and_current_completion_exclusion():
    engine = Phase2BFeatureEngine()
    start = NOW - timedelta(minutes=10)
    engine.precheck(request(1, timestamp=start))
    engine.record_outcome(
        outcome(2, request_sequence=1, timestamp=start + timedelta(seconds=2))
    )
    before = engine._phase2b_snapshot(
        request(3, timestamp=start + timedelta(seconds=10))
    )
    assert before["checkout_completion_lag_available"] == 0
    engine.record_completion(
        completion(4, request_sequence=1, timestamp=start + timedelta(seconds=30))
    )
    after = engine._phase2b_snapshot(
        request(5, timestamp=start + timedelta(seconds=31))
    )
    assert after["checkout_completion_lag_seconds"] == 30
    assert after["checkout_completion_lag_available"] == 1


@pytest.mark.parametrize("window", [timedelta(days=14), timedelta(days=30)])
def test_new_window_is_closed_at_lower_and_open_at_current_boundary(window):
    epsilon = timedelta(microseconds=1)
    engine = Phase2BFeatureEngine()
    engine.devices["device-1"].processed.extend(
        [
            processed(NOW - window - epsilon, card="outside", amount=7),
            processed(NOW - window, card="lower", amount=9),
            processed(NOW - window + epsilon, card="inside", amount=11),
            processed(NOW, card="current"),
        ]
    )
    values = engine._phase2b_snapshot(request(10, card="request-card"))
    if window == timedelta(days=14):
        assert values["prior_attempts_14d"] == 2
        assert values["distinct_cards_14d"] == 3
    else:
        assert values["amount_continuity_history_available"] == 1


def test_duplicate_conflict_late_and_blocked_outcome_behavior():
    engine = Phase2BFeatureEngine()
    first = request(1)
    assert engine.precheck(first) == engine.precheck(first)
    with pytest.raises(ConflictingDuplicateError):
        engine.precheck(first.model_copy(update={"amount": 12.0}))
    with pytest.raises(LateEventError):
        engine.precheck(request(2, timestamp=NOW - timedelta(seconds=1)))

    blocked_engine = Phase2BFeatureEngine()
    blocked_engine.precheck(request(3), blocked=True)
    with pytest.raises(EventContractError, match="blocked"):
        blocked_engine.record_outcome(
            outcome(4, request_sequence=3, timestamp=NOW + timedelta(seconds=1))
        )


def _raw_row(event: LifecycleEvent, **metadata):
    return {
        **event.model_dump(mode="json"),
        "label": 0,
        "population": "normal",
        "attack_subtype": None,
        "scenario_tag": "normal_standard",
        **metadata,
    }


def test_batch_is_deterministic_and_partition_state_isolated():
    first = request(1, device="device-1", ip="shared")
    second = request(2, device="device-2", ip="shared")
    raw = pd.DataFrame([_raw_row(first), _raw_row(second)])
    together, _ = replay_training_events(raw)
    isolated_one, _ = replay_training_events(raw.iloc[[0]])
    isolated_two, _ = replay_training_events(raw.iloc[[1]])
    repeated, _ = replay_training_events(raw)
    pd.testing.assert_frame_equal(together, repeated)
    assert together.iloc[1].requests_per_ip_5m == 2
    assert isolated_one.iloc[0].requests_per_ip_5m == 1
    assert isolated_two.iloc[0].requests_per_ip_5m == 1
