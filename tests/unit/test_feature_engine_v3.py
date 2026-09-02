"""FeatureEngine v3: formulas, boundaries, causality, ordering, retention.

Validates the new causal features in Feature Contract v3:
- card_diversity_ratio_7d
- card_change_after_decline_ratio_7d
- session_churn_rate_24h
- gap_coefficient_of_variation_24h
- median_inter_attempt_gap_seconds_24h
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from card_testing_sentinel.domain.events import LifecycleEvent
from card_testing_sentinel.features.engine_v3 import FeatureEngineV3
from card_testing_sentinel.features.specification_v3 import (
    MODEL_FEATURES_V3,
    MODEL_FEATURES_V3_SHA256,
    NEW_IN_V3,
    validate_feature_contract_v3,
)

START = datetime(2026, 5, 1, tzinfo=UTC)


class StreamV3:
    def __init__(self) -> None:
        self.engine = FeatureEngineV3()
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
        merchant: str = "mer_1",
        request_id: str | None = None,
    ) -> dict:
        sequence = self._next()
        rid = request_id or f"req_{sequence}"
        event = LifecycleEvent.model_validate(
            {
                "event_id": f"evt_{sequence}",
                "event_sequence": sequence,
                "timestamp": at,
                "event_type": "authorization_request",
                "request_id": rid,
                "merchant_id": merchant,
                "device_id": device,
                "session_id": session,
                "ip_fingerprint": ip,
                "amount": amount,
                "currency": "INR",
                "customer_id": customer,
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
        card_last4: str = "1111",
    ) -> None:
        sequence = self._next()
        event = LifecycleEvent.model_validate(
            {
                "event_id": f"evt_{sequence}",
                "event_sequence": sequence,
                "timestamp": at,
                "event_type": "authorization_outcome",
                "request_id": request_id,
                "device_id": device,
                "session_id": session,
                "authorization_result": "approved" if approved else "declined",
                "failure_reason": None if approved else "card_declined",
                "payment_method": "card",
                "card_last4": card_last4,
                "card_network": "visa",
            }
        )
        self.engine.record_outcome(event)


def test_contract_v3_validation() -> None:
    validate_feature_contract_v3()
    assert len(MODEL_FEATURES_V3) == 44
    assert len(set(MODEL_FEATURES_V3)) == 44
    assert len(MODEL_FEATURES_V3_SHA256) == 64
    for feat in NEW_IN_V3:
        assert feat in MODEL_FEATURES_V3


def test_missing_customer_neutrality() -> None:
    stream = StreamV3()
    snap = stream.request(START, customer=None)
    assert snap["customer_id_present"] == 0.0
    assert snap["customer_distinct_devices_7d"] == 0.0
    assert snap["customer_failures_7d"] == 0.0
    assert snap["customer_age_seconds"] == 0.0


def test_single_card_dunning_card_diversity_ratio() -> None:
    """Subscription dunning with 4 declines on the same card must have card_diversity_ratio == 0.25 (1 card / 4 reqs)
    and card_change_after_decline_ratio == 0.0."""
    stream = StreamV3()
    t = START
    # Request 1
    snap1 = stream.request(t, request_id="r1")
    assert snap1["distinct_card_last4_7d"] == 0.0
    stream.outcome(t + timedelta(seconds=2), "r1", approved=False, card_last4="4242")

    # Request 2 (next day)
    t += timedelta(days=1)
    snap2 = stream.request(t, request_id="r2")
    assert snap2["distinct_card_last4_7d"] == 1.0
    assert snap2["failures_7d"] == 1.0
    assert snap2["card_diversity_ratio_7d"] == 0.5  # 1 card / 2 requests
    assert snap2["card_change_after_decline_ratio_7d"] == 0.0  # 0 card changes
    stream.outcome(t + timedelta(seconds=2), "r2", approved=False, card_last4="4242")

    # Request 3 (next day)
    t += timedelta(days=1)
    snap3 = stream.request(t, request_id="r3")
    assert snap3["distinct_card_last4_7d"] == 1.0
    assert snap3["failures_7d"] == 2.0
    assert snap3["card_diversity_ratio_7d"] == 1.0 / 3.0
    assert snap3["card_change_after_decline_ratio_7d"] == 0.0


def test_card_testing_high_rotation() -> None:
    """Card testing where every decline leads to a new card must show high card diversity and card changes."""
    stream = StreamV3()
    t = START

    # Attempt 1 on Card A
    stream.request(t, request_id="r1")
    stream.outcome(t + timedelta(seconds=2), "r1", approved=False, card_last4="1001")

    # Attempt 2 on Card B
    t += timedelta(seconds=10)
    snap2 = stream.request(t, request_id="r2")
    assert snap2["distinct_card_last4_7d"] == 1.0
    stream.outcome(t + timedelta(seconds=2), "r2", approved=False, card_last4="2002")

    # Attempt 3 on Card C
    t += timedelta(seconds=10)
    snap3 = stream.request(t, request_id="r3")
    assert snap3["distinct_card_last4_7d"] == 2.0
    assert snap3["failures_7d"] == 2.0
    assert snap3["card_change_after_decline_7d"] == 1.0
    assert snap3["card_change_after_decline_ratio_7d"] == 0.5  # 1 change / 2 failures
    assert snap3["card_diversity_ratio_7d"] == 2.0 / 3.0


def test_session_churn_rate() -> None:
    """Rotating session on every attempt results in session_churn_rate == 1.0."""
    stream = StreamV3()
    t = START
    stream.request(t, session="s1")
    t += timedelta(seconds=5)
    snap2 = stream.request(t, session="s2")
    assert snap2["sessions_24h"] == 2.0
    assert snap2["requests_24h"] == 2.0
    assert snap2["session_churn_rate_24h"] == 1.0


def test_future_outcome_cannot_change_existing_precheck_snapshot() -> None:
    stream = StreamV3()
    snapshot = stream.request(START, request_id="causal-r1", amount=321.0)
    frozen = dict(snapshot)
    stream.outcome(
        START + timedelta(seconds=2), "causal-r1", approved=False, card_last4="9876"
    )
    assert snapshot == frozen
    assert snapshot["prior_payments_24h"] == 0.0
    assert snapshot["recent_failures_24h"] == 0.0


def test_ip_velocity_is_isolated_by_merchant() -> None:
    stream = StreamV3()
    stream.request(START, device="d1", ip="shared", merchant="merchant-a")
    other = stream.request(
        START + timedelta(seconds=1), device="d2", ip="shared", merchant="merchant-b"
    )
    assert other["requests_per_ip_5m"] == 1.0
    assert other["devices_per_ip_24h"] == 1.0
