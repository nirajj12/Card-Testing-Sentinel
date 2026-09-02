"""Deterministic causal feature engine, version 3.

Preserves the strict causal boundary:
Every snapshot is computed from merchant-visible pre-checkout information:
- The raw facts on the current request
- This device's own earlier requests
- This device's earlier verified payment outcomes and checkouts
- This customer's earlier requests, verified outcomes and checkouts
- New in v3.1: Card diversity ratio, card change ratio after decline,
  session churn rate, 24h gap variability, and 24h median gap.

No feature uses the current attempt's card, method, issuer, decline reason
or result, and none uses any future event.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime, timedelta
from statistics import mean, median, pstdev

import numpy as np

from card_testing_sentinel.domain.events import (
    ConflictingDuplicateError,
    EventContractError,
    LifecycleEvent,
)
from card_testing_sentinel.domain.exceptions import CausalOrderingError
from card_testing_sentinel.features.specification_v3 import (
    CUSTOMER_MISSING_NEUTRAL,
    GAP_STATISTICS,
    MODEL_FEATURES_V3,
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

_REQUEST_CUSTOMER_CAP = 50_000
_IP_MARK_CAP = 4_096


class FeatureEngineV3:
    def __init__(self) -> None:
        self.devices: dict[str, DeviceStateV2] = defaultdict(DeviceStateV2)
        self.customers: dict[str, CustomerState] = defaultdict(CustomerState)
        self.pending: dict[str, PendingRequestV2] = {}
        # IP velocity is merchant-scoped: one merchant may not consume another
        # merchant's traffic history at precheck time.
        self.ip_requests: dict[tuple[str, str], list[tuple[datetime, int, str]]] = defaultdict(list)
        self._digests: dict[str, str] = {}
        self._results: dict[str, dict | None] = {}
        self._request_customer: dict[str, str | None] = {}

    @staticmethod
    def _digest(event: LifecycleEvent) -> str:
        return hashlib.sha256(
            json.dumps(event.model_dump(mode="json"), sort_keys=True).encode()
        ).hexdigest()

    @staticmethod
    def _order(event: LifecycleEvent) -> tuple[str, int]:
        return event.timestamp.isoformat(), event.event_sequence

    def _dedup(self, event: LifecycleEvent) -> tuple[bool, dict | None]:
        prev = self._digests.get(event.event_id)
        if prev is None:
            return False, None
        if prev != self._digest(event):
            raise ConflictingDuplicateError(f"conflicting event {event.event_id}")
        return True, self._results.get(event.event_id)

    def _assert_in_order(self, event: LifecycleEvent, key: str | None) -> None:
        state = self.devices[event.device_id]
        order = self._order(event)
        if state.last_order is not None and order <= state.last_order:
            raise CausalOrderingError(
                f"device {event.device_id}: event {order} arrived after {state.last_order}"
            )
        if key is not None:
            account = self.customers[key]
            if account.last_order is not None and order <= account.last_order:
                raise CausalOrderingError(
                    f"customer {key[:8]}..: event {order} arrived after {account.last_order}"
                )

    def _remember(self, event: LifecycleEvent, result: dict | None, key: str | None) -> None:
        self._digests[event.event_id] = self._digest(event)
        self._results[event.event_id] = result
        order = self._order(event)
        self.devices[event.device_id].last_order = order
        if key is not None:
            self.customers[key].last_order = order

    def _remember_request_customer(self, request_id: str, key: str | None) -> None:
        if len(self._request_customer) >= _REQUEST_CUSTOMER_CAP:
            oldest = next(iter(self._request_customer))
            del self._request_customer[oldest]
        self._request_customer[request_id] = key

    def _prune(self, now: datetime, device_id: str, key: str | None) -> None:
        state = self.devices[device_id]
        cutoff = now - _DEVICE_WINDOW
        state.requests = [r for r in state.requests if r.timestamp >= cutoff]
        state.processed = [p for p in state.processed if p.timestamp >= cutoff]
        state.checkout_times = [t for t in state.checkout_times if t >= cutoff]
        state.session_starts = {
            s: t for s, t in state.session_starts.items() if t >= cutoff
        }
        if key is not None:
            account = self.customers[key]
            c_cutoff = now - _CUSTOMER_WINDOW
            account.devices = [d for d in account.devices if d[0] >= c_cutoff]
            account.failures = [f for f in account.failures if f >= c_cutoff]
            account.checkouts = [c for c in account.checkouts if c >= c_cutoff]

    def _gaps_in_window(self, state: DeviceStateV2, now: datetime) -> list[float]:
        window_start = now - _GAP_WINDOW
        times = [r.timestamp for r in state.requests if r.timestamp >= window_start] + [now]
        times.sort()
        return [
            (t2 - t1).total_seconds()
            for t1, t2 in zip(times[:-1], times[1:])
            if (t2 - t1).total_seconds() > 0.0
        ]

    def _customer_snapshot(self, key: str | None, now: datetime) -> dict[str, float]:
        if key is None:
            return {
                "customer_id_present": 0.0,
                "customer_distinct_devices_7d": CUSTOMER_MISSING_NEUTRAL,
                "customer_failures_7d": CUSTOMER_MISSING_NEUTRAL,
                "customer_successful_checkouts_30d": CUSTOMER_MISSING_NEUTRAL,
                "customer_age_seconds": CUSTOMER_MISSING_NEUTRAL,
            }
        account = self.customers[key]
        seven_days = now - _7D
        thirty_days = now - _30D
        devices_7d = {
            device_id for timestamp, device_id, _ in account.devices if timestamp >= seven_days
        }
        failures_7d = sum(1 for timestamp in account.failures if timestamp >= seven_days)
        checkouts_30d = sum(1 for timestamp in account.checkouts if timestamp >= thirty_days)
        age = (now - account.first_seen).total_seconds() if account.first_seen else 0.0
        return {
            "customer_id_present": 1.0,
            "customer_distinct_devices_7d": float(len(devices_7d)),
            "customer_failures_7d": float(failures_7d),
            "customer_successful_checkouts_30d": float(checkouts_30d),
            "customer_age_seconds": max(0.0, float(age)),
        }

    def snapshot(self, event: LifecycleEvent) -> dict[str, float]:
        state = self.devices[event.device_id]
        now = event.timestamp
        key = customer_key(event.customer_id)

        prior = state.requests
        req_10s = [r for r in prior if now - _10S <= r.timestamp <= now]
        req_60s = [r for r in prior if now - _60S <= r.timestamp <= now]
        req_5m = [r for r in prior if now - _5M <= r.timestamp <= now]
        req_24h = [r for r in prior if now - _24H <= r.timestamp <= now]
        req_7d = [r for r in prior if now - _7D <= r.timestamp <= now]

        boundary_5m = now - _5M
        ip_key = (event.merchant_id, event.ip_fingerprint)
        ip_5m_records = [
            r for r in self.ip_requests.get(ip_key, []) if r[0] >= boundary_5m
        ]
        boundary_24h = now - _24H
        ip_24h_records = [
            r for r in self.ip_requests.get(ip_key, []) if r[0] >= boundary_24h
        ]
        devices_on_ip_24h = {r[2] for r in ip_24h_records} | {event.device_id}

        ips_24h = {r.ip for r in req_24h} | {event.ip_fingerprint}
        amounts_24h = [r.amount for r in req_24h] + [event.amount]

        session_start = state.session_starts.get(event.session_id, now)

        proc_24h = [p for p in state.processed if now - _24H <= p.timestamp <= now]
        declines_24h = [p for p in proc_24h if not p.approved]
        last_payment = state.processed[-1].timestamp if state.processed else None
        successes = [p.timestamp for p in state.processed if p.approved]
        last_success = successes[-1] if successes else None

        retried = 0
        for decline in declines_24h:
            after = [
                r for r in prior if decline.timestamp < r.timestamp <= decline.timestamp + RETRY_WINDOW
            ]
            if after:
                retried += 1

        proc_7d = [p for p in state.processed if now - _7D <= p.timestamp <= now]
        cards_7d = [p.card_last4 for p in proc_7d if p.card_last4 is not None]
        networks_7d = [p.card_network for p in proc_7d if p.card_network is not None]
        failures_7d = sum(1 for p in proc_7d if not p.approved)

        card_changes = 0
        for index in range(len(proc_7d) - 1):
            curr = proc_7d[index]
            nxt = proc_7d[index + 1]
            if (
                not curr.approved
                and curr.card_last4 is not None
                and nxt.card_last4 is not None
                and curr.card_last4 != nxt.card_last4
            ):
                card_changes += 1

        active_days = {r.timestamp.date() for r in req_7d} | {now.date()}
        active_day_count = len(active_days)

        # Gap statistics (v2)
        gaps = self._gaps_in_window(state, now)
        prior_requests = len(prior)
        if prior_requests < _MIN_PRIOR_FOR_MEDIAN or not gaps:
            median_gap = _GAP_NEUTRAL
        else:
            median_gap = float(median(gaps))

        if len(gaps) < _MIN_GAPS_FOR_VARIABILITY:
            gap_variability = _GAP_NEUTRAL
        else:
            gap_variability = float(pstdev(gaps))

        customer = self._customer_snapshot(key, now)

        # ----------------------------------------------------------------------
        # NEW IN V3: Remediation Features
        # ----------------------------------------------------------------------
        # 1. Card Diversity Ratio (7d): distinct cards / total requests
        distinct_cards_7d = len(set(cards_7d))
        total_requests_7d = len(req_7d) + 1
        card_diversity_ratio_7d = float(distinct_cards_7d) / max(1.0, float(total_requests_7d))

        # 2. Card Change After Decline Ratio (7d): card changes / total failures
        card_change_after_decline_ratio_7d = (
            float(card_changes) / float(failures_7d) if failures_7d > 0 else 0.0
        )

        # 3. Session Churn Rate (24h): distinct sessions / total requests
        distinct_sessions_24h = len(
            {s for s, t in state.session_starts.items() if now - _24H <= t <= now}
            | {event.session_id}
        )
        total_requests_24h = len(req_24h) + 1
        session_churn_rate_24h = float(distinct_sessions_24h) / max(1.0, float(total_requests_24h))

        # 4. Gap Coefficient of Variation (24h): std(gaps) / mean(gaps)
        times_24h = [r.timestamp for r in req_24h] + [now]
        times_24h.sort()
        gaps_24h = [
            (t2 - t1).total_seconds()
            for t1, t2 in zip(times_24h[:-1], times_24h[1:])
            if (t2 - t1).total_seconds() > 0.0
        ]
        if len(gaps_24h) >= 2:
            m_gap = float(mean(gaps_24h))
            s_gap = float(pstdev(gaps_24h))
            gap_cov_24h = s_gap / m_gap if m_gap > 0.0 else 0.0
        else:
            gap_cov_24h = 0.0

        # 5. Median Inter-Attempt Gap (24h)
        median_inter_attempt_gap_24h = float(median(gaps_24h)) if gaps_24h else 0.0

        values = {
            "requests_10s": len(req_10s) + 1,
            "requests_60s": len(req_60s) + 1,
            "requests_5m": len(req_5m) + 1,
            "requests_24h": len(req_24h) + 1,
            "requests_per_ip_5m": len(ip_5m_records) + 1,
            "devices_per_ip_24h": len(devices_on_ip_24h),
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
            "sessions_24h": distinct_sessions_24h,
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
            "distinct_card_last4_7d": distinct_cards_7d,
            "distinct_card_networks_7d": len(set(networks_7d)),
            "card_change_after_decline_7d": card_changes,
            "requests_7d": total_requests_7d,
            "failures_7d": failures_7d,
            "active_day_count_7d": active_day_count,
            "failures_per_active_day_7d": failures_7d / active_day_count,
            "median_gap_between_attempts": median_gap,
            "gap_variability": gap_variability,
            **customer,
            "card_diversity_ratio_7d": card_diversity_ratio_7d,
            "card_change_after_decline_ratio_7d": card_change_after_decline_ratio_7d,
            "session_churn_rate_24h": session_churn_rate_24h,
            "gap_coefficient_of_variation_24h": gap_cov_24h,
            "median_inter_attempt_gap_seconds_24h": median_inter_attempt_gap_24h,
        }
        return {name: float(values[name]) for name in MODEL_FEATURES_V3}

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
        boundary = event.timestamp - _24H
        ip_key = (event.merchant_id, event.ip_fingerprint)
        marks = self.ip_requests[ip_key]
        marks.append((event.timestamp, event.event_sequence, event.device_id))
        if len(marks) > _IP_MARK_CAP or marks[0][0] < boundary:
            self.ip_requests[ip_key] = [
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
        if approved:
            state.decline_streak = 0
        else:
            state.decline_streak += 1

        if key is not None and not approved:
            self.customers[key].failures.append(pending.timestamp)

        state.state_version += 1
        self._remember(event, None, key)
        del self.pending[event.request_id]
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
        key = self._request_customer.get(event.request_id)
        self._assert_in_order(event, key)

        state.checkout_times.append(event.timestamp)
        state.state_version += 1

        if key is not None:
            self.customers[key].checkouts.append(event.timestamp)

        self._remember(event, None, key)
        self._prune(event.timestamp, event.device_id, key)
