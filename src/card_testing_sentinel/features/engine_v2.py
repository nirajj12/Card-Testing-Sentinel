"""Deterministic causal feature engine, version 2.

v1 (``features/engine.py``) is untouched and still serves the frozen Model v1.
This is a parallel engine for Feature Contract v2.

What changed, and why:

* **Customer state.** v1 was device-scoped with a thin 24h IP side-channel, so
  one campaign spread across several devices was invisible. v2 keeps a
  customer entity keyed by a one-way digest.
* **Long horizons.** Every v1 count capped at 24 hours, so an attacker with a
  one-day gap reset every counter. v2 adds 7-day and 30-day aggregates.
* **Aged success.** ``successful_checkouts`` was unbounded, so a warm-up phase
  bought permanent credit. v2 uses ``successful_checkouts_30d``.

Causal guarantee, unchanged: a snapshot for attempt N is built from attempts
1..N-1 only. The current request stays in ``pending`` until its own verified
outcome arrives, so no feature can see the current attempt's card, method,
issuer, decline reason or result -- and none can see a future event.

Ordering is enforced per device AND per customer. Customer state spans
devices, so an event that is late against its own account is rejected exactly
as a device-late event is.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime, timedelta
from statistics import mean, median, pstdev

from card_testing_sentinel.domain.events import (
    ConflictingDuplicateError,
    EventContractError,
    LifecycleEvent,
)
from card_testing_sentinel.domain.exceptions import CausalOrderingError
from card_testing_sentinel.features.specification_v2 import (
    CUSTOMER_MISSING_NEUTRAL,
    GAP_STATISTICS,
    MODEL_FEATURES_V2,
    RETENTION,
)
from card_testing_sentinel.features.state_v2 import (
    CustomerState,
    DeviceStateV2,
    PendingRequestV2,
    ProcessedPayment,
    RequestMark,
    customer_key,
)

_10S = timedelta(seconds=10)
_60S = timedelta(seconds=60)
_5M = timedelta(minutes=5)
_24H = timedelta(hours=24)
_7D = timedelta(days=7)
_30D = timedelta(days=30)

LOW_AMOUNT_FLOOR = 5.0
RETRY_WINDOW = timedelta(seconds=120)

_DEVICE_WINDOW = timedelta(days=int(RETENTION["device_history_days"]))
_CUSTOMER_WINDOW = timedelta(days=int(RETENTION["customer_history_days"]))
_CUSTOMER_CAP = int(RETENTION["max_customer_entries"])
_GAP_WINDOW = timedelta(days=int(GAP_STATISTICS["window_days"]))
_MIN_PRIOR_FOR_MEDIAN = int(GAP_STATISTICS["min_prior_requests_for_median"])
_MIN_GAPS_FOR_VARIABILITY = int(GAP_STATISTICS["min_gaps_for_variability"])
_GAP_NEUTRAL = float(GAP_STATISTICS["neutral_value"])
#: Bounds on the two auxiliary indexes that are not per-entity state.
_REQUEST_CUSTOMER_CAP = 50_000
_IP_MARK_CAP = 4_096


class FeatureEngineV2:
    def __init__(self) -> None:
        self.devices: dict[str, DeviceStateV2] = defaultdict(DeviceStateV2)
        self.customers: dict[str, CustomerState] = defaultdict(CustomerState)
        self.pending: dict[str, PendingRequestV2] = {}
        self.ip_requests: dict[str, list[tuple[datetime, int, str]]] = defaultdict(list)
        self._digests: dict[str, str] = {}
        self._results: dict[str, dict | None] = {}
        # request_id -> customer digest, so a checkout (which arrives after
        # its outcome, when the pending record is gone) can still be
        # attributed. FIFO-capped so it cannot grow without bound.
        self._request_customer: dict[str, str | None] = {}

    # -- dedup + ordering ---------------------------------------------------

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

    def _assert_in_order(self, event: LifecycleEvent, key: str | None) -> None:
        """Late against its own device, or against its own account, is late.

        v1 only had the device check. Customer state spans devices, so a
        second ordering guard is required or an out-of-order event on one
        device could silently corrupt another device's customer context.
        """
        order = self._order(event)
        device_last = self.devices[event.device_id].last_order
        if device_last is not None and order < device_last:
            raise CausalOrderingError(
                "event is older than this device's committed state"
            )
        if key is not None:
            customer_last = self.customers[key].last_order
            if customer_last is not None and order < customer_last:
                raise CausalOrderingError(
                    "event is older than this customer's committed state"
                )

    def _remember(
        self, event: LifecycleEvent, result: dict | None, key: str | None
    ) -> None:
        order = self._order(event)
        self._digests[event.event_id] = self._digest(event)
        self._results[event.event_id] = result
        self.devices[event.device_id].last_order = order
        if key is not None:
            self.customers[key].last_order = order

    # -- snapshot -----------------------------------------------------------

    def snapshot(self, event: LifecycleEvent) -> dict[str, float]:
        now = event.timestamp
        order = self._order(event)
        state = self.devices[event.device_id]
        key = customer_key(event.customer_id)

        prior = [
            r
            for r in state.requests
            if (r.timestamp.isoformat(), r.event_sequence) < order
        ]

        def in_window(span: timedelta) -> list[RequestMark]:
            return [r for r in prior if now - span <= r.timestamp <= now]

        req_24h = in_window(_24H)
        req_7d = in_window(_7D)
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
        declines_7d = [p for p in proc_7d if not p.approved]
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
        card_changes = sum(
            bool(
                not a.approved
                and a.card_last4
                and b.card_last4
                and a.card_last4 != b.card_last4
            )
            for a, b in zip(ordered_7d, ordered_7d[1:], strict=False)
        )

        # -- long-horizon device behaviour (new in v2) ----------------------
        # Distinct UTC calendar days this device was active in the last 7,
        # including today: six attempts over six days is a very different
        # shape from six attempts in one afternoon, and no 24h counter can
        # tell them apart.
        active_days = {r.timestamp.date() for r in req_7d} | {now.date()}
        active_day_count = len(active_days)
        failures_7d = len(declines_7d)

        gap_points = [
            r.timestamp for r in prior if now - _GAP_WINDOW <= r.timestamp <= now
        ]
        gap_points.append(now)
        gaps = [
            (later - earlier).total_seconds()
            for earlier, later in zip(gap_points, gap_points[1:], strict=False)
        ]
        prior_in_gap_window = len(gap_points) - 1
        median_gap = (
            float(median(gaps))
            if prior_in_gap_window >= _MIN_PRIOR_FOR_MEDIAN
            else _GAP_NEUTRAL
        )
        average_gap = mean(gaps) if gaps else 0.0
        gap_variability = (
            float(pstdev(gaps) / average_gap)
            if len(gaps) >= _MIN_GAPS_FOR_VARIABILITY and average_gap > 0
            else _GAP_NEUTRAL
        )

        # -- customer context (new in v2) -----------------------------------
        # When the request carries no customer identity every one of these
        # takes the documented neutral value AND `customer_id_present` is 0,
        # so a model can represent "information unavailable" rather than
        # inferring "risky" from an absent account.
        if key is None:
            customer = {
                "customer_id_present": 0.0,
                "customer_distinct_devices_7d": CUSTOMER_MISSING_NEUTRAL,
                "customer_failures_7d": CUSTOMER_MISSING_NEUTRAL,
                "customer_successful_checkouts_30d": CUSTOMER_MISSING_NEUTRAL,
                "customer_age_seconds": CUSTOMER_MISSING_NEUTRAL,
            }
        else:
            account = self.customers.get(key)
            prior_devices = (
                {
                    device
                    for stamp, device, mark_order in account.devices
                    if mark_order < order and now - _7D <= stamp <= now
                }
                if account
                else set()
            )
            customer = {
                "customer_id_present": 1.0,
                "customer_distinct_devices_7d": float(
                    len(prior_devices | {event.device_id})
                ),
                "customer_failures_7d": float(
                    len(
                        [
                            stamp
                            for stamp in (account.failures if account else [])
                            if now - _7D <= stamp <= now
                        ]
                    )
                ),
                "customer_successful_checkouts_30d": float(
                    len(
                        [
                            stamp
                            for stamp in (account.checkouts if account else [])
                            if now - _30D <= stamp <= now
                        ]
                    )
                ),
                "customer_age_seconds": float(
                    (now - account.first_seen).total_seconds()
                    if account and account.first_seen
                    else 0.0
                ),
            }

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
            "successful_checkouts_30d": len(
                [t for t in state.checkout_times if now - _30D <= t <= now]
            ),
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
            "requests_7d": len(req_7d) + 1,
            "failures_7d": failures_7d,
            "active_day_count_7d": active_day_count,
            "failures_per_active_day_7d": failures_7d / active_day_count,
            "median_gap_between_attempts": median_gap,
            "gap_variability": gap_variability,
            **customer,
        }
        return {name: float(values[name]) for name in MODEL_FEATURES_V2}

    # -- record -------------------------------------------------------------

    def record_request(self, event: LifecycleEvent, *, blocked: bool = False) -> dict:
        if event.event_type != "authorization_request":
            raise EventContractError("record_request needs an authorization_request")
        duplicate, stored = self._dedup(event)
        if duplicate:
            return dict(stored or {})
        if event.request_id in self.pending:
            raise EventContractError("request_id is already pending")
        key = customer_key(event.customer_id)
        self._assert_in_order(event, key)

        snapshot = self.snapshot(event)
        state = self.devices[event.device_id]
        order = self._order(event)
        state.requests.append(
            RequestMark(
                event.timestamp,
                event.event_sequence,
                event.session_id,
                event.ip_fingerprint,
                event.amount,
            )
        )
        # IP history only ever feeds 5m/24h features, so it is pruned to 24h
        # on the way in: shared egress addresses would otherwise accumulate
        # every device that ever used them.
        boundary = event.timestamp - _24H
        marks = self.ip_requests[event.ip_fingerprint]
        marks.append((event.timestamp, event.event_sequence, event.device_id))
        if len(marks) > _IP_MARK_CAP or marks[0][0] < boundary:
            self.ip_requests[event.ip_fingerprint] = [
                row for row in marks[-_IP_MARK_CAP:] if row[0] >= boundary
            ]
        state.session_starts.setdefault(event.session_id, event.timestamp)
        if state.first_request_at is None:
            state.first_request_at = event.timestamp
        state.state_version += 1

        if key is not None:
            account = self.customers[key]
            if account.first_seen is None:
                account.first_seen = event.timestamp
            account.devices.append((event.timestamp, event.device_id, order))

        self.pending[event.request_id] = PendingRequestV2(
            request_id=event.request_id,
            event_id=event.event_id,
            timestamp=event.timestamp,
            event_sequence=event.event_sequence,
            device_id=event.device_id,
            session_id=event.session_id,
            ip=event.ip_fingerprint,
            amount=event.amount,
            customer_key=key,
            blocked=blocked,
        )
        self._remember_request_customer(event.request_id, key)
        result = {
            "request_id": event.request_id,
            "state_version": state.state_version,
            **snapshot,
        }
        self._remember(event, result, key)
        self._prune(event.timestamp, event.device_id, key)
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
        # The outcome does not repeat the customer identity, so it is
        # attributed through the pending record it belongs to.
        key = pending.customer_key
        self._assert_in_order(event, key)

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
        if key is not None and not approved:
            self.customers[key].failures.append(pending.timestamp)
        del self.pending[event.request_id]
        self._remember(event, None, key)
        self._prune(event.timestamp, event.device_id, key)

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
        key = self._checkout_customer(event.request_id)
        self._assert_in_order(event, key)
        state.checkout_times.append(event.timestamp)
        state.state_version += 1
        if key is not None:
            self.customers[key].checkouts.append(event.timestamp)
        self._remember(event, None, key)
        self._prune(event.timestamp, event.device_id, key)

    def _checkout_customer(self, request_id: str) -> str | None:
        """A checkout arrives after its outcome, so the pending record is gone.

        The customer digest is recovered from the request's own committed
        history rather than trusting anything on the checkout event -- a
        checkout_completion carries no customer identity.
        """
        return self._request_customer.get(request_id)

    def _remember_request_customer(self, request_id: str, key: str | None) -> None:
        self._request_customer[request_id] = key
        overflow = len(self._request_customer) - _REQUEST_CUSTOMER_CAP
        if overflow > 0:
            for stale in list(self._request_customer)[:overflow]:
                del self._request_customer[stale]

    # -- retention ----------------------------------------------------------

    def _prune(self, now: datetime, device_id: str, key: str | None) -> None:
        """Bounded state: prune to the longest window any feature needs."""
        self.devices[device_id].prune(now, _DEVICE_WINDOW, RETENTION)
        if key is not None:
            self.customers[key].prune(now, _CUSTOMER_WINDOW, _CUSTOMER_CAP)

    def prune_ip_history(self, now: datetime) -> None:
        """IP history is shared across devices, so it is pruned explicitly."""
        boundary = now - _24H
        for ip, rows in list(self.ip_requests.items()):
            kept = [row for row in rows if row[0] >= boundary]
            if kept:
                self.ip_requests[ip] = kept
            else:
                del self.ip_requests[ip]

    def state_size(self) -> dict[str, int]:
        """Retained-state census, for the retention report."""
        device_events = [
            len(s.requests) + len(s.processed) + len(s.checkout_times)
            for s in self.devices.values()
        ]
        customer_events = [
            len(c.devices) + len(c.failures) + len(c.checkouts)
            for c in self.customers.values()
        ]
        return {
            "devices": len(self.devices),
            "customers": len(self.customers),
            "max_device_events": max(device_events, default=0),
            "max_customer_events": max(customer_events, default=0),
            "total_device_events": sum(device_events),
            "total_customer_events": sum(customer_events),
            "ip_keys": len(self.ip_requests),
        }
