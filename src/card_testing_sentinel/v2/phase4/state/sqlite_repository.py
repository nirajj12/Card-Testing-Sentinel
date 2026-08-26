"""Transactional SQLite repository for the local single-process prototype."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from card_testing_sentinel.v2.phase4.exceptions import DuplicateConflictError
from card_testing_sentinel.v2.phase4.state.models import StoredEvent, StoredRequest

SCHEMA = """
CREATE TABLE IF NOT EXISTS requests (
    request_id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL UNIQUE,
    device_hash TEXT NOT NULL,
    session_hash TEXT NOT NULL,
    ip_hash TEXT NOT NULL,
    card_hash TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    event_sequence INTEGER NOT NULL CHECK(event_sequence >= 0),
    payload_digest TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    decision TEXT NOT NULL CHECK(decision IN ('allow', 'review', 'block')),
    raw_score REAL NOT NULL,
    risk_score REAL NOT NULL,
    rule_score INTEGER NOT NULL,
    reason_codes_json TEXT NOT NULL,
    state_version INTEGER NOT NULL CHECK(state_version >= 1),
    response_json TEXT NOT NULL,
    latency_ms REAL NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS lifecycle_events (
    event_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,
    event_type TEXT NOT NULL
        CHECK(event_type IN ('authorization_outcome', 'checkout_completion')),
    device_hash TEXT NOT NULL,
    session_hash TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    event_sequence INTEGER NOT NULL CHECK(event_sequence >= 0),
    payload_digest TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    state_version INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(request_id) REFERENCES requests(request_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_event_transition
ON lifecycle_events(request_id, event_type);
CREATE INDEX IF NOT EXISTS ix_requests_device_order
ON requests(device_hash, timestamp, event_sequence);
CREATE INDEX IF NOT EXISTS ix_events_device_order
ON lifecycle_events(device_hash, timestamp, event_sequence);
CREATE INDEX IF NOT EXISTS ix_requests_session ON requests(session_hash);
CREATE TABLE IF NOT EXISTS runtime_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
INSERT OR REPLACE INTO runtime_metadata(key, value)
VALUES ('schema_version', 'v2-phase4-state-1');
"""


class SQLiteStateRepository:
    store_type = "sqlite"

    def __init__(self, path: Path):
        self.path = path
        self.initialized = False

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
            connection.executescript(SCHEMA)
        self.initialized = True

    def close(self) -> None:
        self.initialized = False

    def get_request(self, request_id: str) -> StoredRequest | None:
        return self._request_query("request_id", request_id)

    def get_request_by_event(self, event_id: str) -> StoredRequest | None:
        return self._request_query("event_id", event_id)

    def _request_query(self, column: str, value: str) -> StoredRequest | None:
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT * FROM requests WHERE {column}=?", (value,)
            ).fetchone()
        return self._request_record(row) if row else None

    def get_event(self, event_id: str) -> StoredEvent | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM lifecycle_events WHERE event_id=?", (event_id,)
            ).fetchone()
        return self._event_record(row) if row else None

    def get_event_for_request(
        self, request_id: str, event_type: str
    ) -> StoredEvent | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM lifecycle_events WHERE request_id=? AND event_type=?",
                (request_id, event_type),
            ).fetchone()
        return self._event_record(row) if row else None

    def save_request(self, request: StoredRequest) -> None:
        columns = tuple(request.__dataclass_fields__)
        values = tuple(getattr(request, name) for name in columns)
        placeholders = ",".join("?" for _ in columns)
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    f"INSERT INTO requests ({','.join(columns)}) "
                    f"VALUES ({placeholders})",
                    values,
                )
        except sqlite3.IntegrityError as error:
            raise DuplicateConflictError("request identifier already exists") from error

    def save_event(self, event: StoredEvent) -> None:
        columns = tuple(event.__dataclass_fields__)
        values = tuple(getattr(event, name) for name in columns)
        placeholders = ",".join("?" for _ in columns)
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    f"INSERT INTO lifecycle_events ({','.join(columns)}) "
                    f"VALUES ({placeholders})",
                    values,
                )
        except sqlite3.IntegrityError as error:
            raise DuplicateConflictError(
                "lifecycle transition already exists"
            ) from error

    def requests_in_order(self) -> list[StoredRequest]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM requests ORDER BY timestamp, event_sequence"
            ).fetchall()
        return [self._request_record(row) for row in rows]

    def events_in_order(self) -> list[StoredEvent]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM lifecycle_events ORDER BY timestamp, event_sequence"
            ).fetchall()
        return [self._event_record(row) for row in rows]

    def latest_order(self) -> tuple[str, int] | None:
        query = """
        SELECT timestamp, event_sequence FROM (
            SELECT timestamp, event_sequence FROM requests
            UNION ALL
            SELECT timestamp, event_sequence FROM lifecycle_events
        ) ORDER BY timestamp DESC, event_sequence DESC LIMIT 1
        """
        with self._connect() as connection:
            row = connection.execute(query).fetchone()
        return (row["timestamp"], row["event_sequence"]) if row else None

    def decisions(self, limit: int) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM requests "
                "ORDER BY timestamp DESC, event_sequence DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._safe_request(self._request_record(row)) for row in rows]

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
        if not self.path.exists():
            return {"type": self.store_type, "initialized": False}
        with self._connect() as connection:
            mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
            requests = connection.execute("SELECT COUNT(*) FROM requests").fetchone()[0]
            events = connection.execute(
                "SELECT COUNT(*) FROM lifecycle_events"
            ).fetchone()[0]
            integrity = connection.execute("PRAGMA quick_check").fetchone()[0]
        return {
            "type": self.store_type,
            "initialized": self.initialized,
            "wal_mode": mode.lower() == "wal",
            "integrity": integrity,
            "requests": requests,
            "events": events,
        }

    @staticmethod
    def _request_record(row: sqlite3.Row) -> StoredRequest:
        return StoredRequest(
            **{name: row[name] for name in StoredRequest.__dataclass_fields__}
        )

    @staticmethod
    def _event_record(row: sqlite3.Row) -> StoredEvent:
        return StoredEvent(
            **{name: row[name] for name in StoredEvent.__dataclass_fields__}
        )

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
