"""Verify Phase 4 runtime semantics and build its append-only hash manifest."""

from __future__ import annotations

import argparse
import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from card_testing_sentinel.common.atomic_io import atomic_write_json, atomic_write_text
from card_testing_sentinel.v2.phase4.app import create_app
from card_testing_sentinel.v2.phase4.artifact_registry import (
    MODEL_SHA256,
    PHASE3_FREEZE_SHA256,
    PHASE3_MANIFEST_SHA256,
    POLICY_SHA256,
    sha256_file,
)
from card_testing_sentinel.v2.phase4.state.sqlite_repository import (
    SQLiteStateRepository,
)

ROOT = Path(__file__).resolve().parents[3]
ARTIFACT_DIR = ROOT / "artifacts/v2/phase4"
REPORT_PATH = ARTIFACT_DIR / "verification_report.json"
MANIFEST_PATH = ARTIFACT_DIR / "phase4_hash_manifest.json"
MANIFEST_DIGEST_PATH = ARTIFACT_DIR / "phase4_hash_manifest.sha256"
VERIFY_SECRET = "phase4-verification-isolated-secret-2026"


def _payload() -> dict:
    return {
        "request_id": "phase4-verification-request-0001",
        "event_id": "phase4-verification-event-0001",
        "device_id": "phase4-verification-device",
        "session_id": "phase4-verification-session",
        "card_reference": "phase4-fake-gateway-token",
        "card_bin": "410000",
        "ip_reference": "phase4-fake-opaque-ip-reference",
        "amount": 2.0,
        "currency": "USD",
        "timestamp": datetime(2036, 1, 1, tzinfo=UTC).isoformat(),
        "event_sequence": 1,
        "campaign_active": False,
    }


def verify_runtime() -> dict:
    payload = _payload()
    with tempfile.TemporaryDirectory(prefix="cts-phase4-verify-") as temporary:
        database = Path(temporary) / "live_state.sqlite3"
        app = create_app(
            repository=SQLiteStateRepository(database),
            hmac_secret=VERIFY_SECRET,
        )
        with TestClient(app) as client:
            readiness = client.get("/health/ready")
            first = client.post("/api/v2/precheck", json=payload)
            retry = client.post("/api/v2/precheck", json=payload)
            conflict = client.post("/api/v2/precheck", json={**payload, "amount": 3.0})
            blind_calls_before = app.state.phase4.service.model_score_calls
            blind = client.get("/api/v2/metrics/blind")
            replay = client.get("/api/v2/replay/devices", params={"limit": 1})
            blind_calls_after = app.state.phase4.service.model_score_calls
            database_status = app.state.phase4.service.repository.status()
            first_body = first.json()
            retry_body = retry.json()
        restarted = create_app(
            repository=SQLiteStateRepository(database),
            hmac_secret=VERIFY_SECRET,
        )
        with TestClient(restarted) as client:
            recovered = client.post("/api/v2/precheck", json=payload)
            recovered_timeline = client.get(
                "/api/v2/runtime/devices/phase4-verification-device/timeline"
            )
            restart_score_calls = restarted.state.phase4.service.model_score_calls
        assertions = {
            "readiness": readiness.status_code == 200
            and readiness.json().get("ready") is True,
            "safe_precheck_http_200": first.status_code == 200,
            "identical_retry_same_decision": retry.status_code == 200
            and retry_body.get("decision") == first_body.get("decision"),
            "identical_retry_same_version": retry_body.get("device_state_version")
            == first_body.get("device_state_version"),
            "identical_retry_marked": retry_body.get("idempotent_replay") is True,
            "conflicting_retry_http_409": conflict.status_code == 409,
            "sqlite_wal": database_status.get("wal_mode") is True,
            "sqlite_integrity": database_status.get("integrity") == "ok",
            "restart_same_decision": recovered.status_code == 200
            and recovered.json().get("decision") == first_body.get("decision"),
            "restart_same_version": recovered.json().get("device_state_version")
            == first_body.get("device_state_version"),
            "restart_no_rescore": restart_score_calls == 0,
            "restart_timeline_recovered": recovered_timeline.status_code == 200
            and len(recovered_timeline.json().get("items", [])) == 1,
            "blind_metrics_saved": blind.status_code == 200,
            "blind_replay_saved": replay.status_code == 200
            and replay.json().get("rescored") is False,
            "blind_endpoints_do_not_score": blind_calls_after == blind_calls_before,
        }
        if not all(assertions.values()):
            failed = [name for name, passed in assertions.items() if not passed]
            raise RuntimeError(f"Phase 4 verification failed: {failed}")
        return {
            "status": "passed",
            "checks": assertions,
            "decision": first_body.get("decision"),
            "state_version": first_body.get("device_state_version"),
            "risk_score_label": "risk score",
            "database": database_status,
            "protected_hashes": {
                "model": MODEL_SHA256,
                "policy": POLICY_SHA256,
                "phase3_pre_access_freeze": PHASE3_FREEZE_SHA256,
                "phase3_final_manifest": PHASE3_MANIFEST_SHA256,
            },
            "phase3_blind_rerun": "refused_by_startup_verification",
        }


def _manifest_files() -> list[Path]:
    roots = [
        ROOT / "configs/v2/phase4",
        ROOT / "scripts/v2/phase4",
        ROOT / "src/card_testing_sentinel/v2/phase4",
        ROOT / "tests/v2/phase4",
        ROOT / "reports/v2/phase4",
        ARTIFACT_DIR,
    ]
    files: list[Path] = []
    for directory in roots:
        if directory.exists():
            files.extend(path for path in directory.rglob("*") if path.is_file())
    documentation = ROOT / "docs/v2/phase4_live_application.md"
    if documentation.is_file():
        files.append(documentation)
    environment_example = ROOT / ".env.example"
    if environment_example.is_file():
        files.append(environment_example)
    return sorted(
        {
            path
            for path in files
            if "__pycache__" not in path.parts
            and path.suffix not in {".pyc", ".sqlite3", ".sqlite", ".db"}
            and path not in {MANIFEST_PATH, MANIFEST_DIGEST_PATH}
        }
    )


def build_manifest() -> dict:
    files = _manifest_files()
    if not files:
        raise RuntimeError("Phase 4 manifest scope is empty")
    manifest = {
        "schema_version": "phase4-hash-manifest-v1",
        "release_date": "2026-08-26",
        "scope": "Phase 4 source, config, UI, tests, documentation and evidence",
        "mutable_runtime_sqlite_excluded": True,
        "file_count": len(files),
        "files": {
            path.relative_to(ROOT).as_posix(): {
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            }
            for path in files
        },
    }
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    atomic_write_json(MANIFEST_PATH, manifest)
    atomic_write_text(MANIFEST_DIGEST_PATH, f"{sha256_file(MANIFEST_PATH)}\n")
    return manifest


def verify_manifest() -> dict:
    manifest = json.loads(MANIFEST_PATH.read_text())
    expected_digest = MANIFEST_DIGEST_PATH.read_text().strip()
    if sha256_file(MANIFEST_PATH) != expected_digest:
        raise RuntimeError("Phase 4 manifest digest mismatch")
    mismatches = []
    for relative, metadata in manifest["files"].items():
        path = ROOT / relative
        if not path.is_file() or sha256_file(path) != metadata["sha256"]:
            mismatches.append(relative)
    if mismatches:
        raise RuntimeError(f"Phase 4 manifest drift: {mismatches}")
    return {"status": "passed", "files": len(manifest["files"])}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", action="store_true")
    parser.add_argument("--build-manifest", action="store_true")
    parser.add_argument("--verify-manifest", action="store_true")
    args = parser.parse_args()
    if not any((args.runtime, args.build_manifest, args.verify_manifest)):
        args.runtime = True
    results = {}
    if args.runtime:
        report = verify_runtime()
        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        atomic_write_json(REPORT_PATH, report)
        results["runtime"] = report
    if args.build_manifest:
        results["manifest"] = build_manifest()
    if args.verify_manifest:
        results["manifest_verification"] = verify_manifest()
    print(json.dumps(results, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
