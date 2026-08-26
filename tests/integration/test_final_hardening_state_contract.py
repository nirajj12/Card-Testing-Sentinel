"""Submission-hardening proof over one real file-backed SQLite database."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from card_testing_sentinel.app import create_app
from card_testing_sentinel.persistence.sqlite_repository import SQLiteStateRepository

SECRET = "final-hardening-test-secret-at-least-sixteen-characters"


def _client(db_path):
    return TestClient(
        create_app(
            repository=SQLiteStateRepository(db_path),
            hmac_secret=SECRET,
        )
    )


def test_file_backed_lifecycle_idempotency_block_reset_and_restart(tmp_path):
    db_path = tmp_path / "hardening.sqlite3"

    with _client(db_path) as first:
        system = first.get("/api/system").json()
        assert system["database"]["journal_mode"] == "wal"
        assert system["database"]["integrity"] == "ok"
        assert system["artifact_load_count"] == 1
        assert system["blind_row_load_count"] == 0

        started = first.post("/api/demo/start", json={"scenario": "burst_attacker"})
        assert started.status_code == 200
        demo_id = started.json()["demo_id"]
        rows = []
        for _ in range(started.json()["total_attempts"]):
            step = first.post("/api/demo/step", json={"demo_id": demo_id})
            assert step.status_code == 200
            rows.append(step.json())

        blocked_indexes = [
            index
            for index, row in enumerate(rows)
            if row["operations"]["decision"] == "block"
        ]
        assert blocked_indexes
        first_block = blocked_indexes[0]
        assert first_block < len(rows) - 1
        assert all(row["attempt"]["attempt"] > 0 for row in rows[first_block + 1 :])
        blocked = rows[first_block]
        assert blocked["operations"]["authorization"] == "suppressed"
        assert blocked["operations"]["outcome_status"] is None
        assert blocked["operations"]["checkout_status"] is None

        before_reset = first.get("/api/system").json()["database"]
        reset = first.post("/api/demo/reset")
        assert reset.status_code == 200
        after_reset = first.get("/api/system").json()["database"]
        assert after_reset["requests"] == before_reset["requests"]
        assert after_reset["events"] == before_reset["events"]

        latest_timestamp, latest_sequence = (
            first.app.state.runtime.service.repository.latest_order()
        )
        timestamp = datetime.fromisoformat(latest_timestamp) + timedelta(seconds=1)
        payload = {
            "request_id": "hardening-idempotent-request",
            "event_id": "hardening-idempotent-event",
            "device_id": "hardening-idempotent-device",
            "session_id": "hardening-idempotent-session",
            "card_reference": "hardening-idempotent-card",
            "card_bin": "410000",
            "ip_reference": "hardening-idempotent-network",
            "amount": 2.0,
            "currency": "INR",
            "timestamp": timestamp.isoformat(),
            "event_sequence": latest_sequence + 1,
            "campaign_active": False,
        }
        original = first.post("/api/precheck", json=payload)
        retry = first.post("/api/precheck", json=payload)
        assert original.status_code == retry.status_code == 200
        assert retry.json()["idempotent_replay"] is True
        assert retry.json()["decision"] == original.json()["decision"]
        assert (
            retry.json()["device_state_version"]
            == original.json()["device_state_version"]
        )
        conflict = first.post("/api/precheck", json={**payload, "amount": 3.0})
        assert conflict.status_code == 409

        late = first.post(
            "/api/precheck",
            json={
                **payload,
                "request_id": "hardening-late-request",
                "event_id": "hardening-late-event",
                "timestamp": latest_timestamp,
            },
        )
        assert late.status_code == 409

        blocked_attempt = rows[first_block]["attempt"]["attempt"]
        latest_timestamp, latest_sequence = (
            first.app.state.runtime.service.repository.latest_order()
        )
        forbidden_outcome = first.post(
            "/api/outcomes",
            json={
                "event_id": "hardening-blocked-outcome",
                "request_id": f"{demo_id}_request_{blocked_attempt}",
                "device_id": f"{demo_id}_device",
                "session_id": f"{demo_id}_session1",
                "timestamp": (
                    datetime.fromisoformat(latest_timestamp) + timedelta(seconds=1)
                ).isoformat(),
                "event_sequence": latest_sequence + 1,
                "authorization_result": "declined",
                "decline_reason": "do_not_honor",
            },
        )
        assert forbidden_outcome.status_code == 409

        timeline_before = first.get(
            f"/api/runtime/devices/{demo_id}_device/timeline"
        ).json()["items"]
        counts_before = first.get("/api/system").json()["database"]

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"

    with _client(db_path) as restarted:
        system = restarted.get("/api/system").json()
        assert system["database"]["requests"] == counts_before["requests"]
        assert system["database"]["events"] == counts_before["events"]
        assert system["database"]["journal_mode"] == "wal"
        assert system["database"]["integrity"] == "ok"
        assert system["artifact_load_count"] == 1
        assert system["blind_row_load_count"] == 0
        assert restarted.app.state.runtime.service.model_score_calls == 0
        timeline_after = restarted.get(
            f"/api/runtime/devices/{demo_id}_device/timeline"
        ).json()["items"]
        assert timeline_after == timeline_before
