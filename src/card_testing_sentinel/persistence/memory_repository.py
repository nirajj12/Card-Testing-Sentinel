"""Isolated in-memory repository for tests and demo sessions."""

from __future__ import annotations

import json

from card_testing_sentinel.domain.exceptions import DuplicateConflictError
from card_testing_sentinel.persistence.models import StoredEvent, StoredRequest


class InMemoryStateRepository:
    store_type = "memory"

    def __init__(self) -> None:
        self.requests: dict[str, StoredRequest] = {}
        self.request_events: dict[str, StoredRequest] = {}
        self.events: dict[str, StoredEvent] = {}
        self.initialized = False

    def initialize(self) -> None:
        self.initialized = True

    def close(self) -> None:
        self.initialized = False

    def get_request(self, request_id: str) -> StoredRequest | None:
        return self.requests.get(request_id)

    def get_request_by_event(self, event_id: str) -> StoredRequest | None:
        return self.request_events.get(event_id)

    def get_event(self, event_id: str) -> StoredEvent | None:
        return self.events.get(event_id)

    def get_event_for_request(
        self, request_id: str, event_type: str
    ) -> StoredEvent | None:
        return next(
            (
                event
                for event in self.events.values()
                if event.request_id == request_id and event.event_type == event_type
            ),
            None,
        )

    def save_request(self, request: StoredRequest) -> None:
        if (
            request.request_id in self.requests
            or request.event_id in self.request_events
        ):
            raise DuplicateConflictError("request identifier already exists")
        self.requests[request.request_id] = request
        self.request_events[request.event_id] = request

    def save_event(self, event: StoredEvent) -> None:
        if event.event_id in self.events:
            raise DuplicateConflictError("event identifier already exists")
        if self.get_event_for_request(event.request_id, event.event_type):
            raise DuplicateConflictError("lifecycle transition already exists")
        self.events[event.event_id] = event

    def requests_in_order(self) -> list[StoredRequest]:
        return sorted(
            self.requests.values(),
            key=lambda row: (row.timestamp, row.event_sequence),
        )

    def events_in_order(self) -> list[StoredEvent]:
        return sorted(
            self.events.values(),
            key=lambda row: (row.timestamp, row.event_sequence),
        )

    def latest_order(self) -> tuple[str, int] | None:
        rows = [
            (row.timestamp, row.event_sequence) for row in self.requests.values()
        ] + [(row.timestamp, row.event_sequence) for row in self.events.values()]
        return max(rows) if rows else None

    def decisions(self, limit: int) -> list[dict]:
        rows = list(reversed(self.requests_in_order()))[:limit]
        return [self._safe_request(row) for row in rows]

    def device_timeline(self, device_hash: str) -> list[dict]:
        requests = [
            self._safe_request(row)
            for row in self.requests_in_order()
            if row.device_hash == device_hash
        ]
        events = [
            self._safe_event(row)
            for row in self.events_in_order()
            if row.device_hash == device_hash
        ]
        return sorted(
            [*requests, *events],
            key=lambda row: (row["timestamp"], row["event_sequence"]),
        )

    def status(self) -> dict:
        return {
            "type": self.store_type,
            "initialized": self.initialized,
            "requests": len(self.requests),
            "events": len(self.events),
            "journal_mode": "n/a (in-memory, not file-backed)",
            "wal_mode": False,
        }

    @staticmethod
    def _safe_request(row: StoredRequest) -> dict:
        return {
            "event_id": row.event_id,
            "request_id": row.request_id,
            "event_type": "authorization_request",
            "timestamp": row.timestamp,
            "event_sequence": row.event_sequence,
            "decision": row.decision,
            "risk_score": row.risk_score,
            "rule_score": row.rule_score,
            "reason_codes": json.loads(row.reason_codes_json),
            "state_version": row.state_version,
            "latency_ms": row.latency_ms,
        }

    @staticmethod
    def _safe_event(row: StoredEvent) -> dict:
        payload = json.loads(row.payload_json)
        return {
            "event_id": row.event_id,
            "request_id": row.request_id,
            "event_type": row.event_type,
            "timestamp": row.timestamp,
            "event_sequence": row.event_sequence,
            "authorization_result": payload.get("authorization_result"),
            "state_version": row.state_version,
        }
