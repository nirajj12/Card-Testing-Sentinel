"""Transactional SQLite repository for the local single-process prototype."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from card_testing_sentinel.domain.exceptions import (
    DuplicateConflictError,
    RuntimeStateError,
)
from card_testing_sentinel.persistence.models import (
    StoredEvent,
    StoredGatewayOrder,
    StoredGatewayPayment,
    StoredRequest,
    StoredWebhookDelivery,
)

SCHEMA_VERSION = "card-testing-sentinel-state-3"
PREVIOUS_SCHEMA_VERSION = "card-testing-sentinel-state-2"

SCHEMA = """
CREATE TABLE IF NOT EXISTS requests (
    request_id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL UNIQUE,
    merchant_hash TEXT NOT NULL,
    customer_hash TEXT,
    device_hash TEXT NOT NULL,
    session_hash TEXT NOT NULL,
    ip_hash TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    event_sequence INTEGER NOT NULL CHECK(event_sequence >= 0),
    payload_digest TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    decision TEXT NOT NULL CHECK(decision IN ('allow', 'review', 'block')),
    risk_score REAL,
    rule_score INTEGER NOT NULL,
    reason_codes_json TEXT NOT NULL,
    state_version INTEGER NOT NULL CHECK(state_version >= 1),
    response_json TEXT NOT NULL,
    latency_ms REAL NOT NULL,
    evidence_json TEXT NOT NULL DEFAULT '{}',
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
CREATE TABLE IF NOT EXISTS gateway_orders (
    sentinel_request_id TEXT PRIMARY KEY,
    razorpay_order_id TEXT NOT NULL UNIQUE,
    amount_minor INTEGER NOT NULL CHECK(amount_minor > 0),
    currency TEXT NOT NULL,
    receipt TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    checkout_opened INTEGER NOT NULL DEFAULT 0 CHECK(checkout_opened IN (0, 1)),
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(sentinel_request_id) REFERENCES requests(request_id)
);
CREATE TABLE IF NOT EXISTS gateway_payments (
    razorpay_payment_id TEXT PRIMARY KEY,
    razorpay_order_id TEXT NOT NULL,
    sentinel_request_id TEXT NOT NULL,
    status TEXT NOT NULL,
    signature_verified INTEGER NOT NULL DEFAULT 0
        CHECK(signature_verified IN (0, 1)),
    webhook_verified INTEGER NOT NULL DEFAULT 0
        CHECK(webhook_verified IN (0, 1)),
    history_status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(razorpay_order_id) REFERENCES gateway_orders(razorpay_order_id),
    FOREIGN KEY(sentinel_request_id) REFERENCES requests(request_id)
);
CREATE INDEX IF NOT EXISTS ix_gateway_payments_order
ON gateway_payments(razorpay_order_id);
CREATE INDEX IF NOT EXISTS ix_gateway_payments_request
ON gateway_payments(sentinel_request_id);
CREATE TABLE IF NOT EXISTS webhook_deliveries (
    event_id TEXT PRIMARY KEY,
    payload_digest TEXT NOT NULL,
    event_type TEXT NOT NULL,
    processed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
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
            existing = (
                connection.execute(
                    "SELECT value FROM runtime_metadata WHERE key='schema_version'"
                ).fetchone()
                if self._table_exists(connection, "runtime_metadata")
                else None
            )
            if existing is not None and existing["value"] == PREVIOUS_SCHEMA_VERSION:
                self._migrate_v2_to_v3(connection)
                existing = None
            if existing is not None and existing["value"] != SCHEMA_VERSION:
                raise RuntimeStateError(
                    "runtime state database uses an incompatible schema "
                    f"({existing['value']}); start with a fresh database"
                )
            connection.executescript(SCHEMA)
            connection.execute(
                "INSERT OR REPLACE INTO runtime_metadata(key, value) VALUES "
                "('schema_version', ?)",
                (SCHEMA_VERSION,),
            )
        self.initialized = True

    @staticmethod
    def _migrate_v2_to_v3(connection: sqlite3.Connection) -> None:
        """Preserve existing local runtime data while widening payment state."""
        connection.executescript(
            """
            ALTER TABLE gateway_orders ADD COLUMN checkout_opened INTEGER NOT NULL
                DEFAULT 0 CHECK(checkout_opened IN (0, 1));
            ALTER TABLE gateway_orders ADD COLUMN updated_at TEXT;
            UPDATE gateway_orders SET updated_at = created_at WHERE updated_at IS NULL;
            ALTER TABLE gateway_payments RENAME TO gateway_payments_v2;
            CREATE TABLE gateway_payments (
                razorpay_payment_id TEXT PRIMARY KEY,
                razorpay_order_id TEXT NOT NULL,
                sentinel_request_id TEXT NOT NULL,
                status TEXT NOT NULL,
                signature_verified INTEGER NOT NULL DEFAULT 0,
                webhook_verified INTEGER NOT NULL DEFAULT 0,
                history_status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(razorpay_order_id)
                    REFERENCES gateway_orders(razorpay_order_id),
                FOREIGN KEY(sentinel_request_id) REFERENCES requests(request_id)
            );
            INSERT INTO gateway_payments (
                razorpay_payment_id, razorpay_order_id, sentinel_request_id,
                status, signature_verified, webhook_verified, history_status,
                created_at, updated_at
            )
            SELECT razorpay_payment_id, razorpay_order_id, sentinel_request_id,
                CASE WHEN status = 'verified' THEN 'signature_verified' ELSE status END,
                CASE WHEN status = 'verified' THEN 1 ELSE 0 END,
                0, 'recorded', verified_at, verified_at
            FROM gateway_payments_v2;
            DROP TABLE gateway_payments_v2;
            """
        )

    @staticmethod
    def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
        return (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
            ).fetchone()
            is not None
        )

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

    def get_gateway_order(self, sentinel_request_id: str) -> StoredGatewayOrder | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM gateway_orders WHERE sentinel_request_id=?",
                (sentinel_request_id,),
            ).fetchone()
        return self._gateway_order_record(row) if row else None

    def get_gateway_order_by_id(
        self, razorpay_order_id: str
    ) -> StoredGatewayOrder | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM gateway_orders WHERE razorpay_order_id=?",
                (razorpay_order_id,),
            ).fetchone()
        return self._gateway_order_record(row) if row else None

    def save_gateway_order(self, order: StoredGatewayOrder) -> None:
        columns = tuple(order.__dataclass_fields__)
        values = tuple(getattr(order, name) for name in columns)
        placeholders = ",".join("?" for _ in columns)
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    f"INSERT INTO gateway_orders ({','.join(columns)}) "
                    f"VALUES ({placeholders})",
                    values,
                )
        except sqlite3.IntegrityError as error:
            raise DuplicateConflictError("gateway order already exists") from error

    def mark_gateway_checkout_opened(self, razorpay_order_id: str) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE gateway_orders SET checkout_opened=1, "
                "updated_at=CURRENT_TIMESTAMP WHERE razorpay_order_id=?",
                (razorpay_order_id,),
            )
            if cursor.rowcount != 1:
                raise DuplicateConflictError("gateway order does not exist")

    def update_gateway_order_status(self, razorpay_order_id: str, status: str) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE gateway_orders SET status=?, updated_at=CURRENT_TIMESTAMP "
                "WHERE razorpay_order_id=?",
                (status, razorpay_order_id),
            )
            if cursor.rowcount != 1:
                raise DuplicateConflictError("gateway order does not exist")

    def get_gateway_payment(
        self, razorpay_payment_id: str
    ) -> StoredGatewayPayment | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM gateway_payments WHERE razorpay_payment_id=?",
                (razorpay_payment_id,),
            ).fetchone()
        return self._gateway_payment_record(row) if row else None

    def save_gateway_payment(self, payment: StoredGatewayPayment) -> None:
        existing = self.get_gateway_payment(payment.razorpay_payment_id)
        if existing is not None and (
            existing.razorpay_order_id != payment.razorpay_order_id
            or existing.sentinel_request_id != payment.sentinel_request_id
        ):
            raise DuplicateConflictError("gateway payment already exists")
        columns = tuple(payment.__dataclass_fields__)
        values = tuple(getattr(payment, name) for name in columns)
        placeholders = ",".join("?" for _ in columns)
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    f"INSERT INTO gateway_payments ({','.join(columns)}) "
                    f"VALUES ({placeholders}) "
                    "ON CONFLICT(razorpay_payment_id) DO UPDATE SET "
                    "status=excluded.status, "
                    "signature_verified=excluded.signature_verified, "
                    "webhook_verified=excluded.webhook_verified, "
                    "history_status=excluded.history_status, "
                    "updated_at=CURRENT_TIMESTAMP "
                    "WHERE gateway_payments.razorpay_order_id="
                    "excluded.razorpay_order_id "
                    "AND gateway_payments.sentinel_request_id="
                    "excluded.sentinel_request_id",
                    values,
                )
        except sqlite3.IntegrityError as error:
            raise DuplicateConflictError("gateway payment already exists") from error

    def gateway_payments_for_order(
        self, razorpay_order_id: str
    ) -> list[StoredGatewayPayment]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM gateway_payments WHERE razorpay_order_id=? "
                "ORDER BY updated_at, razorpay_payment_id",
                (razorpay_order_id,),
            ).fetchall()
        return [self._gateway_payment_record(row) for row in rows]

    def get_webhook_delivery(self, event_id: str) -> StoredWebhookDelivery | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM webhook_deliveries WHERE event_id=?", (event_id,)
            ).fetchone()
        return (
            StoredWebhookDelivery(
                event_id=row["event_id"],
                payload_digest=row["payload_digest"],
                event_type=row["event_type"],
            )
            if row
            else None
        )

    def save_webhook_delivery(self, delivery: StoredWebhookDelivery) -> None:
        try:
            with self._connect() as connection:
                connection.execute(
                    "INSERT INTO webhook_deliveries"
                    "(event_id,payload_digest,event_type) "
                    "VALUES (?,?,?)",
                    (delivery.event_id, delivery.payload_digest, delivery.event_type),
                )
        except sqlite3.IntegrityError as error:
            existing = self.get_webhook_delivery(delivery.event_id)
            if existing != delivery:
                raise DuplicateConflictError(
                    "webhook event identifier already exists"
                ) from error

    def recent_activity(self, limit: int) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM requests ORDER BY timestamp DESC, "
                "event_sequence DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._activity(self._request_record(row)) for row in rows]

    def _activity(self, row: StoredRequest) -> dict:
        payload = json.loads(row.payload_json)
        order = self.get_gateway_order(row.request_id)
        payments = (
            self.gateway_payments_for_order(order.razorpay_order_id) if order else []
        )
        rank = {
            "paid": 5,
            "captured": 4,
            "authorized": 3,
            "failed": 2,
            "signature_verified": 1,
        }
        payment = max(payments, key=lambda item: rank.get(item.status, 0), default=None)
        digest = hashlib.sha256(row.request_id.encode()).hexdigest()[:20]
        return {
            "id": digest,
            "protected_reference": digest,
            "timestamp": row.timestamp,
            "amount": float(payload["amount"]),
            "currency": payload["currency"],
            "source": "replay"
            if row.request_id.startswith(("demo_", "traffic_"))
            else "razorpay_test",
            "sentinel_decision": row.decision,
            "risk_score": row.risk_score,
            "reason_codes": json.loads(row.reason_codes_json),
            "evidence": json.loads(row.evidence_json),
            "razorpay_order_created": order is not None,
            "checkout_opened": bool(order and order.checkout_opened),
            "razorpay_payment_status": payment.status if payment else None,
            "signature_verified": any(item.signature_verified for item in payments),
            "webhook_verified": any(item.webhook_verified for item in payments),
            "history_status": payment.history_status if payment else "not_recorded",
            "payment_attempt_count": len(payments),
        }

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
            "journal_mode": mode.lower(),
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
    def _gateway_order_record(row: sqlite3.Row) -> StoredGatewayOrder:
        return StoredGatewayOrder(
            **{name: row[name] for name in StoredGatewayOrder.__dataclass_fields__}
        )

    @staticmethod
    def _gateway_payment_record(row: sqlite3.Row) -> StoredGatewayPayment:
        values = {
            name: bool(row[name])
            if name in {"signature_verified", "webhook_verified"}
            else row[name]
            for name in StoredGatewayPayment.__dataclass_fields__
        }
        return StoredGatewayPayment(**values)

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
