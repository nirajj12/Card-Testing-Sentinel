"""FeatureEngine v2: formulas, boundaries, causality, ordering, retention.

Hand-built event streams, so each assertion pins one formula rather than a
property of the generated dataset.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from card_testing_sentinel.domain.events import LifecycleEvent
from card_testing_sentinel.domain.exceptions import CausalOrderingError
from card_testing_sentinel.features.engine_v2 import FeatureEngineV2
from card_testing_sentinel.features.specification import (
    MODEL_FEATURES,
    MODEL_FEATURES_SHA256,
)
from card_testing_sentinel.features.specification_v2 import (
    CUSTOMER_FEATURES,
    MODEL_FEATURES_V2,
    MODEL_FEATURES_V2_SHA256,
    NEW_IN_V2,
    RETENTION,
    validate_feature_contract_v2,
)
from card_testing_sentinel.features.state_v2 import customer_key

START = datetime(2026, 5, 1, tzinfo=UTC)


class Stream:
    """A tiny event builder so tests read as behaviour, not plumbing."""

    def __init__(self) -> None:
        self.engine = FeatureEngineV2()
        self.sequence = 0

    def _next(self) -> int:
        self.sequence += 1
        return self.sequence

    def request(
        self,
        at: datetime,
        *,
        device: str = "dev_1",
        session: str = "ses_1",
        ip: str = "ip_1",
        amount: float = 100.0,
        customer: str | None = None,
        request_id: str | None = None,
    ) -> dict:
        sequence = self._next()
        rid = request_id or f"req_{sequence}"
        event = LifecycleEvent.model_validate(
            {
                "event_id": f"evt_{sequence}",
                "event_type": "authorization_request",
                "request_id": rid,
                "timestamp": at,
                "event_sequence": sequence,
                "merchant_id": "mer_001",
                "device_id": device,
                "session_id": session,
                "ip_fingerprint": ip,
                "amount": amount,
                "currency": "INR",
                "customer_id": customer,
                "campaign_active": False,
            }
        )
        return self.engine.record_request(event)

    def outcome(
        self,
        at: datetime,
        request_id: str,
        *,
        approved: bool,
        device: str = "dev_1",
        session: str = "ses_1",
        last4: str | None = None,
    ) -> None:
        sequence = self._next()
        self.engine.record_outcome(
            LifecycleEvent.model_validate(
                {
                    "event_id": f"evt_{sequence}",
                    "event_type": "authorization_outcome",
                    "request_id": request_id,
                    "timestamp": at,
                    "event_sequence": sequence,
                    "device_id": device,
                    "session_id": session,
                    "authorization_result": "approved" if approved else "declined",
                    "payment_method": "card",
                    "card_last4": last4 or "4242",
                    "card_network": "visa",
                }
            )
        )

    def checkout(
        self,
        at: datetime,
        request_id: str,
        *,
        device: str = "dev_1",
        session: str = "ses_1",
    ) -> None:
        sequence = self._next()
        self.engine.record_checkout(
            LifecycleEvent.model_validate(
                {
                    "event_id": f"evt_{sequence}",
                    "event_type": "checkout_completion",
                    "request_id": request_id,
                    "timestamp": at,
                    "event_sequence": sequence,
                    "device_id": device,
                    "session_id": session,
                }
            )
        )


# --- the contract itself ----------------------------------------------------


def test_the_contract_is_valid_and_has_thirty_nine_features():
    validate_feature_contract_v2()
    assert len(MODEL_FEATURES_V2) == 39
    assert len(NEW_IN_V2) == 11


def test_v1_and_v2_contracts_are_isolated():
    """The frozen 28-feature model must never receive a 39-feature vector."""
    assert len(MODEL_FEATURES) == 28
    assert MODEL_FEATURES_V2_SHA256 != MODEL_FEATURES_SHA256
    # v1 survives intact inside v2 apart from the one documented rename
    assert set(MODEL_FEATURES) - set(MODEL_FEATURES_V2) == {"successful_checkouts"}
    assert "successful_checkouts_30d" in MODEL_FEATURES_V2


def test_the_snapshot_returns_exactly_the_contract_in_order():
    stream = Stream()
    snapshot = stream.request(START)
    ordered = [name for name in snapshot if name in set(MODEL_FEATURES_V2)]
    assert ordered == list(MODEL_FEATURES_V2)


# --- long-horizon formulas --------------------------------------------------


def test_requests_7d_counts_prior_requests_plus_the_current_one():
    stream = Stream()
    stream.request(START)
    stream.request(START + timedelta(days=2))
    snapshot = stream.request(START + timedelta(days=4))
    assert snapshot["requests_7d"] == 3.0
    # ... and the 24h counter sees only the current attempt
    assert snapshot["requests_24h"] == 1.0


def test_the_seven_day_window_boundary_is_exact():
    stream = Stream()
    stream.request(START)
    inside = stream.request(START + timedelta(days=7) - timedelta(seconds=1))
    assert inside["requests_7d"] == 2.0
    outside = stream.request(START + timedelta(days=7, seconds=1))
    # the first request has now fallen out; only the second remains
    assert outside["requests_7d"] == 2.0


def test_active_day_count_counts_calendar_days_not_attempts():
    stream = Stream()
    for hour in (0, 1, 2):
        stream.request(START + timedelta(hours=hour))
    same_day = stream.request(START + timedelta(hours=3))
    assert same_day["active_day_count_7d"] == 1.0
    assert same_day["requests_7d"] == 4.0

    spread = Stream()
    for day in range(4):
        spread.request(START + timedelta(days=day))
    snapshot = spread.request(START + timedelta(days=4))
    assert snapshot["active_day_count_7d"] == 5.0


def test_failures_7d_and_failures_per_active_day():
    stream = Stream()
    for day in range(3):
        stream.request(START + timedelta(days=day), request_id=f"r{day}")
        stream.outcome(
            START + timedelta(days=day, seconds=5), f"r{day}", approved=False
        )
    snapshot = stream.request(START + timedelta(days=3))
    assert snapshot["failures_7d"] == 3.0
    assert snapshot["active_day_count_7d"] == 4.0
    assert snapshot["failures_per_active_day_7d"] == pytest.approx(3.0 / 4.0)


def test_gap_statistics_need_history_and_are_neutral_without_it():
    stream = Stream()
    first = stream.request(START)
    assert first["median_gap_between_attempts"] == 0.0
    assert first["gap_variability"] == 0.0

    second = stream.request(START + timedelta(seconds=100))
    # one gap only -- still below the documented floor of two prior requests
    assert second["median_gap_between_attempts"] == 0.0

    third = stream.request(START + timedelta(seconds=300))
    # gaps are now [100, 200]
    assert third["median_gap_between_attempts"] == pytest.approx(150.0)
    # variability still needs three gaps
    assert third["gap_variability"] == 0.0

    fourth = stream.request(START + timedelta(seconds=700))
    assert fourth["gap_variability"] > 0.0


def test_a_perfectly_regular_cadence_has_zero_variability():
    stream = Stream()
    for step in range(5):
        snapshot = stream.request(START + timedelta(seconds=60 * step))
    assert snapshot["median_gap_between_attempts"] == pytest.approx(60.0)
    assert snapshot["gap_variability"] == pytest.approx(0.0, abs=1e-9)


def test_successful_checkouts_age_out_after_thirty_days():
    """The v1 feature was unbounded, so a warm-up bought permanent credit."""
    stream = Stream()
    stream.request(START, request_id="r0")
    stream.outcome(START + timedelta(seconds=5), "r0", approved=True)
    stream.checkout(START + timedelta(seconds=10), "r0")

    soon = stream.request(START + timedelta(days=5))
    assert soon["successful_checkouts_30d"] == 1.0

    later = stream.request(START + timedelta(days=31))
    assert later["successful_checkouts_30d"] == 0.0


# --- customer state ---------------------------------------------------------


def test_customer_features_are_neutral_without_an_identity():
    stream = Stream()
    snapshot = stream.request(START)
    assert snapshot["customer_id_present"] == 0.0
    for name in CUSTOMER_FEATURES:
        assert snapshot[name] == 0.0, name


def test_a_legitimate_multi_device_customer_is_counted():
    """One person, phone and laptop -- the anti-leakage case."""
    stream = Stream()
    stream.request(START, device="phone", customer="cus_a")
    snapshot = stream.request(
        START + timedelta(days=1), device="laptop", session="ses_2", customer="cus_a"
    )
    assert snapshot["customer_id_present"] == 1.0
    assert snapshot["customer_distinct_devices_7d"] == 2.0
    # each device on its own still looks brand new
    assert snapshot["requests_7d"] == 1.0
    assert snapshot["is_new_device"] == 1.0


def test_a_cross_device_campaign_accumulates_customer_context():
    stream = Stream()
    for index in range(4):
        rid = f"r{index}"
        stream.request(
            START + timedelta(hours=index),
            device=f"dev_{index}",
            session=f"ses_{index}",
            customer="cus_attack",
            request_id=rid,
        )
        stream.outcome(
            START + timedelta(hours=index, seconds=5),
            rid,
            approved=False,
            device=f"dev_{index}",
            session=f"ses_{index}",
        )
    snapshot = stream.request(
        START + timedelta(hours=5),
        device="dev_new",
        session="ses_new",
        customer="cus_attack",
    )
    assert snapshot["customer_distinct_devices_7d"] == 5.0
    assert snapshot["customer_failures_7d"] == 4.0
    # every individual device still carries almost no history
    assert snapshot["requests_7d"] == 1.0
    assert snapshot["failures_7d"] == 0.0


def test_customer_history_ages_out_of_its_windows():
    stream = Stream()
    stream.request(START, device="d1", customer="cus_a", request_id="r0")
    stream.outcome(START + timedelta(seconds=5), "r0", approved=False, device="d1")
    stream.request(
        START + timedelta(seconds=20), device="d1", customer="cus_a", request_id="r1"
    )
    stream.outcome(START + timedelta(seconds=25), "r1", approved=True, device="d1")
    stream.checkout(START + timedelta(seconds=30), "r1", device="d1")

    within = stream.request(
        START + timedelta(days=3), device="d2", session="s2", customer="cus_a"
    )
    assert within["customer_failures_7d"] == 1.0
    assert within["customer_successful_checkouts_30d"] == 1.0

    beyond = stream.request(
        START + timedelta(days=10), device="d3", session="s3", customer="cus_a"
    )
    assert beyond["customer_failures_7d"] == 0.0  # 7-day window
    assert beyond["customer_successful_checkouts_30d"] == 1.0  # 30-day window


def test_customer_tenure_grows_and_survives_history_pruning():
    stream = Stream()
    stream.request(START, customer="cus_a")
    snapshot = stream.request(
        START + timedelta(days=45), device="d2", session="s2", customer="cus_a"
    )
    assert snapshot["customer_age_seconds"] == pytest.approx(45 * 86400, rel=1e-6)


def test_the_raw_customer_identity_is_never_stored():
    stream = Stream()
    stream.request(START, customer="cus_secret_value")
    assert "cus_secret_value" not in stream.engine.customers
    assert customer_key("cus_secret_value") in stream.engine.customers
    assert customer_key(None) is None


# --- causality --------------------------------------------------------------


def test_the_current_outcome_can_never_reach_its_own_snapshot():
    """The whole product boundary in one assertion."""
    stream = Stream()
    before = stream.request(START, request_id="r0")
    stream.outcome(START + timedelta(seconds=5), "r0", approved=False)
    after = stream.request(START + timedelta(seconds=10))
    assert before["failures_7d"] == 0.0
    assert before["recent_failures_24h"] == 0.0
    assert after["failures_7d"] == 1.0


def test_a_future_event_cannot_influence_an_earlier_snapshot():
    stream = Stream()
    first = stream.request(START, request_id="r0")
    stream.request(START + timedelta(hours=1), request_id="r1")
    stream.outcome(START + timedelta(hours=1, seconds=5), "r1", approved=False)
    replayed = FeatureEngineV2()
    event = LifecycleEvent.model_validate(
        {
            "event_id": "evt_replay",
            "event_type": "authorization_request",
            "request_id": "r0",
            "timestamp": START,
            "event_sequence": 1,
            "merchant_id": "mer_001",
            "device_id": "dev_1",
            "session_id": "ses_1",
            "ip_fingerprint": "ip_1",
            "amount": 100.0,
            "currency": "INR",
            "campaign_active": False,
        }
    )
    assert replayed.snapshot(event)["failures_7d"] == first["failures_7d"]


def test_an_event_older_than_its_device_state_is_rejected():
    stream = Stream()
    stream.request(START + timedelta(hours=2))
    with pytest.raises(CausalOrderingError, match="device"):
        stream.request(START)


def test_an_event_older_than_its_customer_state_is_rejected():
    """v1 only guarded per device; customer state spans devices."""
    stream = Stream()
    stream.request(START + timedelta(hours=2), device="d1", customer="cus_a")
    with pytest.raises(CausalOrderingError, match="customer"):
        stream.request(START, device="d2", session="s2", customer="cus_a")


# --- retention --------------------------------------------------------------


def test_device_and_customer_history_are_pruned_and_capped():
    stream = Stream()
    at = START
    for index in range(120):
        at = START + timedelta(days=index)
        stream.request(at, customer="cus_a", request_id=f"r{index}")
    state = stream.engine.devices["dev_1"]
    account = stream.engine.customers[customer_key("cus_a")]
    horizon = timedelta(days=int(RETENTION["device_history_days"]))
    assert all(mark.timestamp >= at - horizon for mark in state.requests)
    assert len(state.requests) <= int(RETENTION["max_device_requests"])
    assert all(stamp >= at - horizon for stamp, _, _ in account.devices)
    assert len(account.devices) <= int(RETENTION["max_customer_entries"])
    census = stream.engine.state_size()
    assert census["max_device_events"] <= int(RETENTION["max_device_requests"])


# --- backward compatibility -------------------------------------------------


def test_the_frozen_model_still_loads_against_the_v1_contract():
    """Model v1 must remain usable while v2 is under development."""
    from pathlib import Path

    from card_testing_sentinel.modeling.model import READY, RiskModel

    root = Path(__file__).resolve().parents[2]
    model = RiskModel.load(root, allow_degraded=False)
    assert model.status == READY
    assert tuple(model._artifact.feature_names) == MODEL_FEATURES
    assert model._artifact.feature_contract_sha256 == MODEL_FEATURES_SHA256


def test_a_v2_vector_cannot_be_scored_by_the_v1_model():
    """The contract hash is the guard; a 39-length vector must be refused."""
    from pathlib import Path

    from card_testing_sentinel.modeling.model import RiskModel

    root = Path(__file__).resolve().parents[2]
    model = RiskModel.load(root, allow_degraded=False)
    stream = Stream()
    v2_snapshot = stream.request(START)
    assert len(v2_snapshot) > len(MODEL_FEATURES)
    with pytest.raises(KeyError):
        # `score` reads the v1 contract by name; the renamed feature is gone
        model.score({k: v for k, v in v2_snapshot.items() if k in MODEL_FEATURES_V2})
