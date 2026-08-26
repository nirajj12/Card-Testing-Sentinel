"""Thin live adapter over the frozen feature engine, scorer, and stateful policy."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import UTC, datetime

from card_testing_sentinel.v2.data.contracts import LifecycleEvent
from card_testing_sentinel.v2.phase2b.engine import Phase2BFeatureEngine
from card_testing_sentinel.v2.phase2b.features import MODEL_FEATURE_COLUMNS
from card_testing_sentinel.v2.phase2c.policy import StatefulPolicy
from card_testing_sentinel.v2.phase4.artifact_registry import ArtifactRegistry
from card_testing_sentinel.v2.phase4.contracts import (
    CheckoutRequest,
    OutcomeRequest,
    PrecheckRequest,
    PrecheckResponse,
    TransitionResponse,
)
from card_testing_sentinel.v2.phase4.exceptions import (
    CausalOrderingError,
    DuplicateConflictError,
    InvalidLifecycleTransition,
    RuntimeStateError,
)
from card_testing_sentinel.v2.phase4.security import IdentifierProtector, payload_digest
from card_testing_sentinel.v2.phase4.state.models import StoredEvent, StoredRequest
from card_testing_sentinel.v2.phase4.state.repository import StateRepository

LOGGER = logging.getLogger("card_testing_sentinel.phase4")


class LiveScoringService:
    """Single-process, globally serialized causal transition service."""

    def __init__(
        self,
        registry: ArtifactRegistry,
        repository: StateRepository,
        protector: IdentifierProtector,
    ) -> None:
        self.registry = registry
        self.repository = repository
        self.protector = protector
        self.lock = asyncio.Lock()
        self.engine = Phase2BFeatureEngine()
        self.policy = StatefulPolicy(registry.policy)
        self.model_score_calls = 0
        self.repository.initialize()
        self.rebuild_from_persistence()

    @staticmethod
    def _utc(value: datetime) -> datetime:
        return value.astimezone(UTC)

    @classmethod
    def _order(cls, timestamp: datetime, sequence: int) -> tuple[str, int]:
        return cls._utc(timestamp).isoformat(), sequence

    def _assert_not_late(self, timestamp: datetime, sequence: int) -> None:
        latest = self.repository.latest_order()
        if latest is not None and self._order(timestamp, sequence) < latest:
            raise CausalOrderingError("event is older than committed causal state")

    def _request_payload(self, request: PrecheckRequest) -> dict:
        return {
            "event_id": request.event_id,
            "request_id": request.request_id,
            "event_sequence": request.event_sequence,
            "timestamp": self._utc(request.timestamp).isoformat(),
            "event_type": "authorization_request",
            "device_id": self.protector.protect("device", request.device_id),
            "session_id": self.protector.protect("session", request.session_id),
            "ip_fingerprint": self.protector.protect_ip(request.ip_reference),
            "card_fingerprint": self.protector.protect("card", request.card_reference),
            "card_bin": request.card_bin,
            "amount": request.amount,
            "currency": request.currency,
            "campaign_active": request.campaign_active,
        }

    def _outcome_payload(self, request: OutcomeRequest) -> dict:
        return {
            "event_id": request.event_id,
            "request_id": request.request_id,
            "event_sequence": request.event_sequence,
            "timestamp": self._utc(request.timestamp).isoformat(),
            "event_type": "authorization_outcome",
            "device_id": self.protector.protect("device", request.device_id),
            "session_id": self.protector.protect("session", request.session_id),
            "authorization_result": request.authorization_result,
            "decline_reason": request.decline_reason,
        }

    def _checkout_payload(self, request: CheckoutRequest) -> dict:
        return {
            "event_id": request.event_id,
            "request_id": request.request_id,
            "event_sequence": request.event_sequence,
            "timestamp": self._utc(request.timestamp).isoformat(),
            "event_type": "checkout_completion",
            "device_id": self.protector.protect("device", request.device_id),
            "session_id": self.protector.protect("session", request.session_id),
        }

    async def precheck(self, request: PrecheckRequest) -> PrecheckResponse:
        async with self.lock:
            return self._precheck(request)

    def _precheck(self, request: PrecheckRequest) -> PrecheckResponse:
        started = time.perf_counter_ns()
        payload = self._request_payload(request)
        digest = payload_digest(payload)
        existing = self.repository.get_request(request.request_id)
        event_existing = self.repository.get_request_by_event(request.event_id)
        if existing or event_existing:
            stored = existing or event_existing
            if stored.payload_digest != digest:
                raise DuplicateConflictError(
                    "request retry conflicts with stored payload"
                )
            response = json.loads(stored.response_json)
            response["idempotent_replay"] = True
            return PrecheckResponse.model_validate(response)
        if self.repository.get_event(request.event_id):
            raise DuplicateConflictError(
                "event ID is already used by another transition"
            )
        self._assert_not_late(request.timestamp, request.event_sequence)
        event = LifecycleEvent.model_validate(payload)
        state = self.engine.devices[event.device_id]
        snapshot = {
            **self.engine._snapshot(event, state),
            **self.engine._phase2b_snapshot(event),
        }
        raw_score, risk_score = self.registry.scorer.score_snapshot(snapshot)
        self.model_score_calls += 1
        decision = self.policy.decide(
            device_id=event.device_id,
            event_id=event.event_id,
            timestamp=event.timestamp,
            session_id=event.session_id,
            probability=risk_score,
            snapshot=snapshot,
        )
        committed = self.engine.precheck(event, blocked=decision.action == "block")
        if any(committed[name] != snapshot[name] for name in MODEL_FEATURE_COLUMNS):
            raise RuntimeStateError("precheck state changed during decision")
        latency_ms = (time.perf_counter_ns() - started) / 1_000_000
        response = PrecheckResponse(
            request_id=request.request_id,
            event_id=request.event_id,
            decision=decision.action,
            risk_score=risk_score,
            rule_score=decision.rule_score,
            reason_codes=list(decision.reason_codes),
            model_version=self.registry.model_version,
            policy_version=self.registry.policy_version,
            device_state_version=int(committed["state_version"]),
            idempotent_replay=False,
            processed_at=datetime.now(UTC),
            latency_ms=latency_ms,
        )
        stored = StoredRequest(
            request_id=request.request_id,
            event_id=request.event_id,
            device_hash=event.device_id,
            session_hash=event.session_id,
            ip_hash=event.ip_fingerprint,
            card_hash=event.card_fingerprint,
            timestamp=event.timestamp.isoformat(),
            event_sequence=event.event_sequence,
            payload_digest=digest,
            payload_json=json.dumps(payload, sort_keys=True),
            decision=decision.action,
            raw_score=raw_score,
            risk_score=risk_score,
            rule_score=decision.rule_score,
            reason_codes_json=json.dumps(list(decision.reason_codes)),
            state_version=int(committed["state_version"]),
            response_json=response.model_dump_json(),
            latency_ms=latency_ms,
        )
        try:
            self.repository.save_request(stored)
        except Exception:
            self.rebuild_from_persistence()
            raise
        LOGGER.info(
            "precheck decision=%s model=%s policy=%s state_version=%s latency_ms=%.3f",
            decision.action,
            self.registry.model_version,
            self.registry.policy_version,
            stored.state_version,
            latency_ms,
        )
        return response

    async def outcome(self, request: OutcomeRequest) -> TransitionResponse:
        async with self.lock:
            return self._transition(request, "authorization_outcome")

    async def checkout(self, request: CheckoutRequest) -> TransitionResponse:
        async with self.lock:
            return self._transition(request, "checkout_completion")

    def _transition(
        self, request: OutcomeRequest | CheckoutRequest, event_type: str
    ) -> TransitionResponse:
        payload = (
            self._outcome_payload(request)
            if event_type == "authorization_outcome"
            else self._checkout_payload(request)
        )
        digest = payload_digest(payload)
        existing = self.repository.get_event(request.event_id)
        transition = self.repository.get_event_for_request(
            request.request_id, event_type
        )
        if existing or transition:
            stored = existing or transition
            if stored.payload_digest != digest:
                raise DuplicateConflictError(
                    "lifecycle retry conflicts with stored payload"
                )
            return TransitionResponse(
                event_id=request.event_id,
                request_id=request.request_id,
                accepted=True,
                idempotent_replay=True,
                device_state_version=stored.state_version,
                processed_at=datetime.now(UTC),
            )
        if self.repository.get_request_by_event(request.event_id):
            raise DuplicateConflictError("event ID is already used by a request")
        stored_request = self.repository.get_request(request.request_id)
        if stored_request is None:
            raise InvalidLifecycleTransition("request does not exist")
        if (
            stored_request.device_hash != payload["device_id"]
            or stored_request.session_hash != payload["session_id"]
        ):
            raise InvalidLifecycleTransition("transition crosses device or session")
        if stored_request.decision == "block":
            raise InvalidLifecycleTransition(
                "blocked request cannot receive outcome or checkout"
            )
        self._assert_not_late(request.timestamp, request.event_sequence)
        event = LifecycleEvent.model_validate(payload)
        try:
            if event_type == "authorization_outcome":
                self.engine.record_outcome(event)
            else:
                self.engine.record_completion(event)
            version = self.engine.devices[event.device_id].state_version
            self.repository.save_event(
                StoredEvent(
                    event_id=event.event_id,
                    request_id=event.request_id,
                    event_type=event_type,
                    device_hash=event.device_id,
                    session_hash=event.session_id,
                    timestamp=event.timestamp.isoformat(),
                    event_sequence=event.event_sequence,
                    payload_digest=digest,
                    payload_json=json.dumps(payload, sort_keys=True),
                    state_version=version,
                )
            )
        except Exception:
            self.rebuild_from_persistence()
            raise
        return TransitionResponse(
            event_id=event.event_id,
            request_id=event.request_id,
            accepted=True,
            idempotent_replay=False,
            device_state_version=version,
            processed_at=datetime.now(UTC),
        )

    def rebuild_from_persistence(self) -> None:
        self.engine = Phase2BFeatureEngine()
        self.policy = StatefulPolicy(self.registry.policy)
        records = [
            (row.timestamp, row.event_sequence, "request", row)
            for row in self.repository.requests_in_order()
        ] + [
            (row.timestamp, row.event_sequence, "event", row)
            for row in self.repository.events_in_order()
        ]
        for _timestamp, _sequence, kind, row in sorted(records):
            event = LifecycleEvent.model_validate(json.loads(row.payload_json))
            if kind == "request":
                state = self.engine.devices[event.device_id]
                snapshot = {
                    **self.engine._snapshot(event, state),
                    **self.engine._phase2b_snapshot(event),
                }
                decision = self.policy.decide(
                    device_id=event.device_id,
                    event_id=event.event_id,
                    timestamp=event.timestamp,
                    session_id=event.session_id,
                    probability=row.risk_score,
                    snapshot=snapshot,
                )
                if decision.action != row.decision:
                    raise RuntimeStateError("persisted decision does not reproduce")
                committed = self.engine.precheck(event, blocked=row.decision == "block")
                if int(committed["state_version"]) != row.state_version:
                    raise RuntimeStateError("persisted request state version mismatch")
            elif row.event_type == "authorization_outcome":
                self.engine.record_outcome(event)
            else:
                self.engine.record_completion(event)
            if self.engine.devices[event.device_id].state_version != row.state_version:
                raise RuntimeStateError("persisted lifecycle state version mismatch")

    def decisions(self, limit: int) -> list[dict]:
        return self.repository.decisions(limit)

    def timeline(self, raw_device_id: str) -> list[dict]:
        device_hash = self.protector.protect("device", raw_device_id)
        return self.repository.device_timeline(device_hash)

    def close(self) -> None:
        self.repository.close()
