import hashlib
import json
from collections import defaultdict
from datetime import datetime, timedelta
from statistics import pstdev

from card_testing_sentinel.domain.events import (
    ConflictingDuplicateError,
    EventContractError,
    LateEventError,
    LifecycleEvent,
)
from card_testing_sentinel.features.specification import BASE_FEATURES
from card_testing_sentinel.features.state import (
    DeviceState,
    PendingRequest,
    ProcessedAuthorization,
)

WINDOWS = {
    "10s": timedelta(seconds=10),
    "60s": timedelta(seconds=60),
    "5m": timedelta(minutes=5),
    "1h": timedelta(hours=1),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
}


def _within(records, now: datetime, window: timedelta):
    boundary = now - window
    return [record for record in records if boundary <= record.timestamp < now]


class CausalFeatureEngine:
    """Deterministic in-memory lifecycle engine shared by batch and live scoring."""

    def __init__(self):
        self.devices: dict[str, DeviceState] = defaultdict(DeviceState)
        self.pending: dict[str, PendingRequest] = {}
        self.event_digests: dict[str, str] = {}
        self.event_results: dict[str, dict | None] = {}
        self.last_order: dict[str, tuple[datetime, int]] = {}
        self.ip_history: dict[str, list[tuple[datetime, str, str]]] = defaultdict(list)
        self.ip_request_history: dict[str, list[tuple[datetime, int, str]]] = (
            defaultdict(list)
        )

    @staticmethod
    def _digest(event: LifecycleEvent) -> str:
        payload = json.dumps(event.model_dump(mode="json"), sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()

    def _deduplicate(self, event: LifecycleEvent):
        digest = self._digest(event)
        previous = self.event_digests.get(event.event_id)
        if previous is not None:
            if previous != digest:
                raise ConflictingDuplicateError(
                    "event_id reused with different content"
                )
            return True, self.event_results[event.event_id]
        order = (event.timestamp, event.event_sequence)
        if order < self.last_order.get(event.device_id, order):
            raise LateEventError("event is older than committed device state")
        return False, None

    def _remember(self, event: LifecycleEvent, result: dict | None):
        self.event_digests[event.event_id] = self._digest(event)
        self.event_results[event.event_id] = result
        self.last_order[event.device_id] = (event.timestamp, event.event_sequence)

    def precheck(self, event: LifecycleEvent, *, blocked: bool = False) -> dict:
        if event.event_type != "authorization_request":
            raise EventContractError("precheck requires authorization_request")
        duplicate, result = self._deduplicate(event)
        if duplicate:
            return dict(result or {})
        if event.request_id in self.pending:
            raise EventContractError("request_id is already pending")
        state = self.devices[event.device_id]
        snapshot = self._snapshot(event, state)
        state.request_times.append((event.timestamp, event.event_sequence))
        self.ip_request_history[event.ip_fingerprint].append(
            (event.timestamp, event.event_sequence, event.device_id)
        )
        state.session_starts.setdefault(event.session_id, event.timestamp)
        state.state_version += 1
        self.pending[event.request_id] = PendingRequest(
            event_id=event.event_id,
            request_id=event.request_id,
            timestamp=event.timestamp,
            event_sequence=event.event_sequence,
            device_id=event.device_id,
            session_id=event.session_id,
            ip_fingerprint=event.ip_fingerprint,
            card_fingerprint=event.card_fingerprint,
            card_bin=event.card_bin,
            amount=event.amount,
            blocked=blocked,
        )
        result = {
            "event_id": event.event_id,
            "request_id": event.request_id,
            "state_version": state.state_version,
            **snapshot,
        }
        self._remember(event, result)
        return result

    def record_outcome(self, event: LifecycleEvent) -> None:
        if event.event_type != "authorization_outcome":
            raise EventContractError("record_outcome requires authorization_outcome")
        duplicate, _ = self._deduplicate(event)
        if duplicate:
            return
        pending = self.pending.get(event.request_id)
        if pending is None:
            raise EventContractError("outcome has no matching pending request")
        if pending.blocked:
            raise EventContractError("blocked request cannot receive processor outcome")
        if (pending.device_id, pending.session_id) != (
            event.device_id,
            event.session_id,
        ):
            raise EventContractError("outcome crosses device or session")
        if event.timestamp <= pending.timestamp:
            raise EventContractError("outcome must occur after request")
        approved = event.authorization_result == "approved"
        state = self.devices[event.device_id]
        state.processed.append(
            ProcessedAuthorization(
                request_id=pending.request_id,
                timestamp=pending.timestamp,
                session_id=pending.session_id,
                ip_fingerprint=pending.ip_fingerprint,
                card_fingerprint=pending.card_fingerprint,
                card_bin=pending.card_bin,
                amount=pending.amount,
                approved=approved,
            )
        )
        state.decline_streak = 0 if approved else state.decline_streak + 1
        state.state_version += 1
        self.ip_history[pending.ip_fingerprint].append(
            (pending.timestamp, pending.device_id, pending.session_id)
        )
        del self.pending[event.request_id]
        self._remember(event, None)

    def record_completion(self, event: LifecycleEvent) -> None:
        if event.event_type != "checkout_completion":
            raise EventContractError("record_completion requires checkout_completion")
        duplicate, _ = self._deduplicate(event)
        if duplicate:
            return
        state = self.devices[event.device_id]
        approved = [
            record
            for record in state.processed
            if record.request_id == event.request_id and record.approved
        ]
        if not approved or approved[-1].session_id != event.session_id:
            raise EventContractError("completion lacks matching processed approval")
        if event.timestamp <= approved[-1].timestamp:
            raise EventContractError("completion must follow approval request")
        state.checkout_times.append(event.timestamp)
        state.state_version += 1
        self._remember(event, None)

    def _snapshot(self, event: LifecycleEvent, state: DeviceState) -> dict[str, float]:
        now = event.timestamp
        records = state.processed
        recent = {name: _within(records, now, span) for name, span in WINDOWS.items()}
        current_order = (now, event.event_sequence)
        requests = {
            name: [
                time
                for time in state.request_times
                if now - span <= time[0] <= now and time < current_order
            ]
            for name, span in WINDOWS.items()
        }
        prior = records[-1] if records else None
        first_approval = next(
            (i for i, row in enumerate(records) if row.approved), None
        )
        decline_5m = [row for row in recent["5m"] if not row.approved]
        decline_24h = [row for row in recent["24h"] if not row.approved]
        amounts = [row.amount for row in recent["24h"]]
        same_card = [
            row
            for row in recent["24h"]
            if row.card_fingerprint == event.card_fingerprint
        ]
        switches_after_decline = sum(
            not left.approved and left.card_fingerprint != right.card_fingerprint
            for left, right in zip(recent["24h"], recent["24h"][1:], strict=False)
        )
        current_session_start = state.session_starts.get(event.session_id, now)
        prior_session_starts = [
            time
            for session, time in state.session_starts.items()
            if session != event.session_id and time < now
        ]
        ip_recent = [
            row
            for row in self.ip_history[event.ip_fingerprint]
            if now - WINDOWS["5m"] <= row[0] < now
        ]
        ip_requests = [
            row
            for row in self.ip_request_history[event.ip_fingerprint]
            if now - WINDOWS["5m"] <= row[0] <= now
            and (row[0], row[1]) < (now, event.event_sequence)
        ]
        checkouts = [time for time in state.checkout_times if time < now]
        values = {
            "prior_attempts_10s": len(recent["10s"]),
            "prior_attempts_60s": len(recent["60s"]),
            "prior_attempts_5m": len(recent["5m"]),
            "prior_attempts_1h": len(recent["1h"]),
            "prior_attempts_24h": len(recent["24h"]),
            "prior_attempts_7d": len(recent["7d"]),
            "prospective_requests_10s": len(requests["10s"]) + 1,
            "prospective_requests_60s": len(requests["60s"]) + 1,
            "distinct_cards_5m": len(
                {r.card_fingerprint for r in recent["5m"]} | {event.card_fingerprint}
            ),
            "distinct_cards_1h": len(
                {r.card_fingerprint for r in recent["1h"]} | {event.card_fingerprint}
            ),
            "distinct_cards_24h": len(
                {r.card_fingerprint for r in recent["24h"]} | {event.card_fingerprint}
            ),
            "distinct_cards_7d": len(
                {r.card_fingerprint for r in recent["7d"]} | {event.card_fingerprint}
            ),
            "distinct_bins_5m": len(
                {r.card_bin for r in recent["5m"]} | {event.card_bin}
            ),
            "distinct_bins_24h": len(
                {r.card_bin for r in recent["24h"]} | {event.card_bin}
            ),
            "cross_session_cards_24h": len(
                {
                    r.card_fingerprint
                    for r in recent["24h"]
                    if r.session_id != event.session_id
                }
                | {event.card_fingerprint}
            ),
            "cross_session_cards_7d": len(
                {
                    r.card_fingerprint
                    for r in recent["7d"]
                    if r.session_id != event.session_id
                }
                | {event.card_fingerprint}
            ),
            "prior_decline_streak": state.decline_streak,
            "prior_decline_ratio_5m": len(decline_5m) / len(recent["5m"])
            if recent["5m"]
            else 0,
            "prior_decline_ratio_24h": len(decline_24h) / len(recent["24h"])
            if recent["24h"]
            else 0,
            "attempts_before_first_approval": first_approval
            if first_approval is not None
            else len(records),
            "attempts_after_first_approval": len(records) - first_approval - 1
            if first_approval is not None
            else 0,
            "seconds_since_previous_authorization": (
                now - prior.timestamp
            ).total_seconds()
            if prior
            else 0,
            "device_age_seconds": (now - records[0].timestamp).total_seconds()
            if records
            else 0,
            "session_age_seconds": (now - current_session_start).total_seconds(),
            "seconds_since_previous_session": (
                now - max(prior_session_starts)
            ).total_seconds()
            if prior_session_starts
            else 0,
            "sessions_24h": len(
                {
                    s
                    for s, t in state.session_starts.items()
                    if now - WINDOWS["24h"] <= t < now
                }
                | {event.session_id}
            ),
            "sessions_7d": len(
                {
                    s
                    for s, t in state.session_starts.items()
                    if now - WINDOWS["7d"] <= t < now
                }
                | {event.session_id}
            ),
            "ip_changes_24h": sum(
                a.ip_fingerprint != b.ip_fingerprint
                for a, b in zip(recent["24h"], recent["24h"][1:], strict=False)
            )
            + (int(prior.ip_fingerprint != event.ip_fingerprint) if prior else 0),
            "devices_per_ip_5m": len({row[1] for row in ip_recent} | {event.device_id}),
            "requests_per_ip_5m": len(ip_requests) + 1,
            "same_card_retry_ratio_24h": len(same_card) / len(recent["24h"])
            if recent["24h"]
            else 0,
            "card_switches_after_decline_24h": switches_after_decline,
            "current_amount": event.amount,
            "amount_delta_from_previous": event.amount - prior.amount if prior else 0,
            "amount_variation_24h": pstdev(amounts) if len(amounts) > 1 else 0,
            "near_minimum_ratio_24h": sum(amount <= 2 for amount in amounts)
            / len(amounts)
            if amounts
            else 0,
            "prior_successful_checkouts": len(checkouts),
            "seconds_since_successful_checkout": (now - checkouts[-1]).total_seconds()
            if checkouts
            else 0,
            "campaign_active": int(event.campaign_active),
        }
        return {name: float(values[name]) for name in BASE_FEATURES}
