"""Online-compatible Phase 2B feature engine."""

from collections import defaultdict
from datetime import timedelta
from statistics import mean, pstdev

from card_testing_sentinel.v2.data.contracts import EventContractError, LifecycleEvent
from card_testing_sentinel.v2.features.engine import CausalFeatureEngine
from card_testing_sentinel.v2.phase2b.features import NEW_FEATURES

WINDOW_14D = timedelta(days=14)
WINDOW_24H = timedelta(hours=24)
WINDOW_30D = timedelta(days=30)


class Phase2BFeatureEngine(CausalFeatureEngine):
    """Extend frozen Phase 1 state without modifying its protected source."""

    def __init__(self) -> None:
        super().__init__()
        self.checkout_completion_lags: dict[str, list[float]] = defaultdict(list)

    @staticmethod
    def _recent(records, now, window):
        boundary = now - window
        return [record for record in records if boundary <= record.timestamp < now]

    def _phase2b_snapshot(self, event: LifecycleEvent) -> dict[str, float]:
        state = self.devices[event.device_id]
        records_14d = self._recent(state.processed, event.timestamp, WINDOW_14D)
        records_24h = self._recent(state.processed, event.timestamp, WINDOW_24H)
        records_30d = self._recent(state.processed, event.timestamp, WINDOW_30D)

        historical_amounts = [record.amount for record in records_30d]
        amount_std = pstdev(historical_amounts) if len(historical_amounts) >= 2 else 0.0
        amount_available = len(historical_amounts) >= 2 and amount_std > 0
        amount_score = (
            (event.amount - mean(historical_amounts)) / amount_std
            if amount_available
            else 0.0
        )

        device_ips = {record.ip_fingerprint for record in records_24h}
        device_ips.add(event.ip_fingerprint)
        shared_devices = {event.device_id}
        boundary = event.timestamp - WINDOW_24H
        for ip in device_ips:
            shared_devices.update(
                device_id
                for timestamp, device_id, _session_id in self.ip_history[ip]
                if boundary <= timestamp < event.timestamp
            )

        lags = self.checkout_completion_lags[event.device_id]
        values = {
            "prior_attempts_14d": len(records_14d),
            "distinct_cards_14d": len(
                {record.card_fingerprint for record in records_14d}
                | {event.card_fingerprint}
            ),
            "amount_continuity_score_30d": amount_score,
            "amount_continuity_history_available": int(amount_available),
            "ip_rotation_ratio_24h": len(device_ips) / len(shared_devices),
            "checkout_completion_lag_seconds": lags[-1] if lags else 0.0,
            "checkout_completion_lag_available": int(bool(lags)),
        }
        return {name: float(values[name]) for name in NEW_FEATURES}

    def precheck(self, event: LifecycleEvent, *, blocked: bool = False) -> dict:
        if event.event_type != "authorization_request":
            raise EventContractError("precheck requires authorization_request")
        duplicate = event.event_id in self.event_digests
        phase2b = self._phase2b_snapshot(event) if not duplicate else None
        result = super().precheck(event, blocked=blocked)
        if duplicate:
            return result
        combined = {**result, **phase2b}
        self.event_results[event.event_id] = combined
        return combined

    def record_completion(self, event: LifecycleEvent) -> None:
        duplicate = event.event_id in self.event_digests
        state = self.devices[event.device_id]
        matching = [
            record
            for record in state.processed
            if record.request_id == event.request_id and record.approved
        ]
        super().record_completion(event)
        if not duplicate:
            self.checkout_completion_lags[event.device_id].append(
                (event.timestamp - matching[-1].timestamp).total_seconds()
            )
