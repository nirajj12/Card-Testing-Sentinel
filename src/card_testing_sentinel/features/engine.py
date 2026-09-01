"""Deterministic causal feature engine.

One class owns all runtime feature state: it builds a point-in-time snapshot,
records a scored request, records a later verified outcome, records a checkout,
and can be rebuilt by replaying stored events.

Causal guarantee: a snapshot for attempt N is built from attempts 1..N-1 only.
The current request is held in ``pending`` and does not enter ``processed``
until its own verified outcome arrives, so no feature can see the current
attempt's card, payment method, or result.

Ordering is enforced per device (and, for shared-IP features, per IP), never
globally: an event is "late" only against its own device's last committed
event. Independent devices never block each other.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime, timedelta
from statistics import pstdev

from card_testing_sentinel.domain.events import (
    ConflictingDuplicateError,
    EventContractError,
    LifecycleEvent,
)
from card_testing_sentinel.domain.exceptions import CausalOrderingError
from card_testing_sentinel.features.specification import MODEL_FEATURES
from card_testing_sentinel.features.state import (
    DeviceState,
    PendingRequest,
    ProcessedPayment,
    RequestMark,
)

_10S = timedelta(seconds=10)
_60S = timedelta(seconds=60)
_5M = timedelta(minutes=5)
_24H = timedelta(hours=24)
_7D = timedelta(days=7)

#: A request amount at or below this (in the request currency's minor-unit
#: scale) is treated as "near floor". Card testing tends to use tiny amounts,
#: but so do some legitimate flows -- this is a weak tendency, not a label.
LOW_AMOUNT_FLOOR = 5.0

#: How quickly a fresh request after a decline counts as a "retry".
RETRY_WINDOW = timedelta(seconds=120)


class FeatureEngine:
    def __init__(self) -> None:
        self.devices: dict[str, DeviceState] = defaultdict(DeviceState)
        self.pending: dict[str, PendingRequest] = {}
        self.ip_requests: dict[str, list[tuple[datetime, int, str]]] = defaultdict(list)
        self._digests: dict[str, str] = {}
        self._results: dict[str, dict | None] = {}

    # -- dedup + per-device ordering -----------------------------------------

    @staticmethod
    def _digest(event: LifecycleEvent) -> str:
        return hashlib.sha256(
            json.dumps(event.model_dump(mode="json"), sort_keys=True).encode()
        ).hexdigest()

    @staticmethod
    def _order(event: LifecycleEvent) -> tuple[str, int]:
        return event.timestamp.isoformat(), event.event_sequence

    def _dedup(self, event: LifecycleEvent) -> tuple[bool, dict | None]:
        digest = self._digest(event)
        seen = self._digests.get(event.event_id)
        if seen is not None:
            if seen != digest:
                raise ConflictingDuplicateError(
                    "event_id reused with different content"
                )
            return True, self._results[event.event_id]
        return False, None

    def _assert_in_order(self, event: LifecycleEvent) -> None:
        last = self.devices[event.device_id].last_order
        if last is not None and self._order(event) < last:
            raise CausalOrderingError(
                "event is older than this device's committed state"
            )

    def _remember(self, event: LifecycleEvent, result: dict | None) -> None:
        self._digests[event.event_id] = self._digest(event)
        self._results[event.event_id] = result
        self.devices[event.device_id].last_order = self._order(event)

    # -- snapshot ----------------------------------------------------------

    def snapshot(self, event: LifecycleEvent) -> dict[str, float]:
        now = event.timestamp
        order = self._order(event)
        state = self.devices[event.device_id]

        prior = [
            r
            for r in state.requests
            if (r.timestamp.isoformat(), r.event_sequence) < order
        ]

        def in_window(span: timedelta) -> list[RequestMark]:
            return [r for r in prior if now - span <= r.timestamp <= now]

        req_24h = in_window(_24H)
        amounts_24h = [r.amount for r in req_24h] + [event.amount]
        ips_24h = {r.ip for r in req_24h} | {event.ip_fingerprint}

        ip_5m = [
            row
            for row in self.ip_requests.get(event.ip_fingerprint, [])
            if now - _5M <= row[0] <= now and (row[0].isoformat(), row[1]) < order
        ]
        ip_24h = [
            row
            for row in self.ip_requests.get(event.ip_fingerprint, [])
            if now - _24H <= row[0] <= now and (row[0].isoformat(), row[1]) < order
        ]

        proc_24h = [p for p in state.processed if now - _24H <= p.timestamp <= now]
        proc_7d = [p for p in state.processed if now - _7D <= p.timestamp <= now]
        declines_24h = [p for p in proc_24h if not p.approved]
        retried = sum(
            any(
                timedelta() < mark.timestamp - decline.timestamp <= RETRY_WINDOW
                for mark in [
                    *req_24h,
                    RequestMark(now, event.event_sequence, "", "", 0.0),
                ]
            )
            for decline in declines_24h
        )
        last_payment = max((p.timestamp for p in state.processed), default=None)
        last_success = max((t for t in state.checkout_times if t <= now), default=None)
        session_start = state.session_starts.get(event.session_id, now)

        cards_7d = [p.card_last4 for p in proc_7d if p.card_last4]
        networks_7d = [p.card_network for p in proc_7d if p.card_network]
        ordered_7d = sorted(proc_7d, key=lambda p: p.timestamp)
        # bool() matters: a non-card outcome (UPI, wallet) has no last4, and a
        # bare `and` chain would yield None rather than False and break sum().
        card_changes = sum(
            bool(
                not a.approved
                and a.card_last4
                and b.card_last4
                and a.card_last4 != b.card_last4
            )
            for a, b in zip(ordered_7d, ordered_7d[1:], strict=False)
        )

        values = {
            "requests_10s": len(in_window(_10S)) + 1,
            "requests_60s": len(in_window(_60S)) + 1,
            "requests_5m": len(in_window(_5M)) + 1,
            "requests_24h": len(req_24h) + 1,
            "requests_per_ip_5m": len(ip_5m) + 1,
            "devices_per_ip_24h": len({row[2] for row in ip_24h} | {event.device_id}),
            "seconds_since_last_request": (
                (now - prior[-1].timestamp).total_seconds() if prior else 0.0
            ),
            "ip_changes_24h": len(ips_24h) - 1,
            "device_age_seconds": (
                (now - state.first_request_at).total_seconds()
                if state.first_request_at
                else 0.0
            ),
            "is_new_device": 0.0 if state.requests else 1.0,
            "session_age_seconds": (now - session_start).total_seconds(),
            "sessions_24h": len(
                {s for s, t in state.session_starts.items() if now - _24H <= t <= now}
                | {event.session_id}
            ),
            "ip_rotation_ratio_24h": len(ips_24h) / (len(req_24h) + 1),
            "prior_payments_24h": len(proc_24h),
            "recent_failures_24h": len(declines_24h),
            "failure_ratio_24h": (
                len(declines_24h) / len(proc_24h) if proc_24h else 0.0
            ),
            "decline_streak": state.decline_streak,
            "successful_checkouts": len([t for t in state.checkout_times if t <= now]),
            "seconds_since_last_payment": (
                (now - last_payment).total_seconds() if last_payment else 0.0
            ),
            "seconds_since_last_success": (
                (now - last_success).total_seconds() if last_success else 0.0
            ),
            "retry_after_decline_ratio_24h": (
                retried / len(declines_24h) if declines_24h else 0.0
            ),
            "current_amount": event.amount,
            "amount_delta": event.amount - prior[-1].amount if prior else 0.0,
            "amount_variation_24h": (
                pstdev(amounts_24h) if len(amounts_24h) > 1 else 0.0
            ),
            "low_amount_ratio_24h": sum(
                amount <= LOW_AMOUNT_FLOOR for amount in amounts_24h
            )
            / len(amounts_24h),
            "distinct_card_last4_7d": len(set(cards_7d)),
            "distinct_card_networks_7d": len(set(networks_7d)),
            "card_change_after_decline_7d": card_changes,
        }
        return {name: float(values[name]) for name in MODEL_FEATURES}

    # -- record ----------------------------------------------------------

    def record_request(self, event: LifecycleEvent, *, blocked: bool = False) -> dict:
        if event.event_type != "authorization_request":
            raise EventContractError("record_request needs an authorization_request")
        duplicate, stored = self._dedup(event)
        if duplicate:
            return dict(stored or {})
        if event.request_id in self.pending:
            raise EventContractError("request_id is already pending")
        self._assert_in_order(event)

        snapshot = self.snapshot(event)
        state = self.devices[event.device_id]
        state.requests.append(
            RequestMark(
                event.timestamp,
                event.event_sequence,
                event.session_id,
                event.ip_fingerprint,
                event.amount,
            )
        )
        self.ip_requests[event.ip_fingerprint].append(
            (event.timestamp, event.event_sequence, event.device_id)
        )
        state.session_starts.setdefault(event.session_id, event.timestamp)
        if state.first_request_at is None:
            state.first_request_at = event.timestamp
        state.state_version += 1
        self.pending[event.request_id] = PendingRequest(
            request_id=event.request_id,
            event_id=event.event_id,
            timestamp=event.timestamp,
            event_sequence=event.event_sequence,
            device_id=event.device_id,
            session_id=event.session_id,
            ip=event.ip_fingerprint,
            amount=event.amount,
            blocked=blocked,
        )
        result = {
            "request_id": event.request_id,
            "state_version": state.state_version,
            **snapshot,
        }
        self._remember(event, result)
        return result

    def record_outcome(self, event: LifecycleEvent) -> None:
        if event.event_type != "authorization_outcome":
            raise EventContractError("record_outcome needs an authorization_outcome")
        duplicate, _ = self._dedup(event)
        if duplicate:
            return
        pending = self.pending.get(event.request_id)
        if pending is None:
            raise EventContractError("outcome has no matching pending request")
        if pending.blocked:
            raise EventContractError("blocked request cannot receive an outcome")
        if (pending.device_id, pending.session_id) != (
            event.device_id,
            event.session_id,
        ):
            raise EventContractError("outcome crosses device or session")
        if event.timestamp <= pending.timestamp:
            raise EventContractError("outcome must occur after its request")
        self._assert_in_order(event)

        approved = event.authorization_result == "approved"
        state = self.devices[event.device_id]
        state.processed.append(
            ProcessedPayment(
                request_id=pending.request_id,
                timestamp=pending.timestamp,
                session_id=pending.session_id,
                ip=pending.ip,
                amount=pending.amount,
                approved=approved,
                payment_method=event.payment_method,
                card_last4=event.card_last4,
                card_network=event.card_network,
                card_type=event.card_type,
                card_issuer=event.card_issuer,
                international=event.international,
            )
        )
        state.decline_streak = 0 if approved else state.decline_streak + 1
        state.state_version += 1
        del self.pending[event.request_id]
        self._remember(event, None)

    def record_checkout(self, event: LifecycleEvent) -> None:
        if event.event_type != "checkout_completion":
            raise EventContractError("record_checkout needs a checkout_completion")
        duplicate, _ = self._dedup(event)
        if duplicate:
            return
        state = self.devices[event.device_id]
        approved = [
            p
            for p in state.processed
            if p.request_id == event.request_id and p.approved
        ]
        if not approved or approved[-1].session_id != event.session_id:
            raise EventContractError("checkout has no matching approved payment")
        if event.timestamp <= approved[-1].timestamp:
            raise EventContractError("checkout must follow its approved request")
        self._assert_in_order(event)
        state.checkout_times.append(event.timestamp)
        state.state_version += 1
        self._remember(event, None)
