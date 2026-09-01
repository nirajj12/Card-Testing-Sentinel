"""Merchant-side risk service.

One globally serialised path: validate -> protect identifiers -> check
idempotency -> build causal features -> score -> decide -> persist. Verified
outcomes and checkouts arrive later and only change future decisions.

The policy is the validation-selected operating point; the service supplies
it with the request's merchant context (`campaign_active`) and the device's
recent risk history, then records the decision.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import UTC, datetime

from card_testing_sentinel.api.contracts import (
    CheckoutRequest,
    OutcomeRequest,
    PrecheckRequest,
    PrecheckResponse,
    TransitionResponse,
)
from card_testing_sentinel.domain.events import LifecycleEvent
from card_testing_sentinel.domain.exceptions import (
    DuplicateConflictError,
    InvalidLifecycleTransition,
    RuntimeStateError,
)
from card_testing_sentinel.features.engine_v2 import FeatureEngineV2
from card_testing_sentinel.features.specification_v2 import MODEL_FEATURES_V2
from card_testing_sentinel.modeling.registry import ArtifactRegistry
from card_testing_sentinel.persistence.models import StoredEvent, StoredRequest
from card_testing_sentinel.persistence.repository import StateRepository
from card_testing_sentinel.policy.engine_v2 import RiskPolicyV2
from card_testing_sentinel.security.identifiers import (
    IdentifierProtector,
    payload_digest,
)
from card_testing_sentinel.services.operations_projection import safe_evidence

LOGGER = logging.getLogger("card_testing_sentinel.risk")


def _utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


class RiskService:
    """Single-process, per-device-ordered causal decision service."""

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
        self.engine = FeatureEngineV2()
        self.policy = RiskPolicyV2(registry.policy)
        self.model_score_calls = 0
        self.repository.initialize()
        self.rebuild_from_persistence()

    # -- payload normalisation -------------------------------------------

    def _request_payload(self, request: PrecheckRequest) -> dict:
        payload = {
            "event_id": request.event_id,
            "request_id": request.request_id,
            "event_sequence": request.event_sequence,
            "timestamp": _utc(request.timestamp).isoformat(),
            "event_type": "authorization_request",
            "merchant_id": self.protector.protect("merchant", request.merchant_id),
            "device_id": self.protector.protect("device", request.device_id),
            "session_id": self.protector.protect("session", request.session_id),
            "ip_fingerprint": self.protector.protect_ip(request.ip_reference),
            "amount": request.amount,
            "currency": request.currency,
            "campaign_active": request.campaign_active,
        }
        if request.customer_id is not None:
            payload["customer_id"] = self.protector.protect(
                "customer", request.customer_id
            )
        return payload

    def _outcome_payload(self, request: OutcomeRequest) -> dict:
        payload = {
            "event_id": request.event_id,
            "request_id": request.request_id,
            "event_sequence": request.event_sequence,
            "timestamp": _utc(request.timestamp).isoformat(),
            "event_type": "authorization_outcome",
            "device_id": self.protector.protect("device", request.device_id),
            "session_id": self.protector.protect("session", request.session_id),
            "authorization_result": request.authorization_result,
            "failure_reason": request.failure_reason,
            "payment_method": request.payment_method,
            "card_last4": request.card_last4,
            "card_network": request.card_network,
            "card_type": request.card_type,
            "card_issuer": request.card_issuer,
            "international": request.international,
        }
        return {key: value for key, value in payload.items() if value is not None}

    def _checkout_payload(self, request: CheckoutRequest) -> dict:
        return {
            "event_id": request.event_id,
            "request_id": request.request_id,
            "event_sequence": request.event_sequence,
            "timestamp": _utc(request.timestamp).isoformat(),
            "event_type": "checkout_completion",
            "device_id": self.protector.protect("device", request.device_id),
            "session_id": self.protector.protect("session", request.session_id),
        }

    # -- precheck -------------------------------------------------------

    async def precheck(self, request: PrecheckRequest) -> PrecheckResponse:
        async with self.lock:
            return self._precheck(request)

    async def precheck_with_evidence(
        self, request: PrecheckRequest
    ) -> tuple[PrecheckResponse, dict]:
        async with self.lock:
            sink: dict = {}
            return self._precheck(request, evidence_sink=sink), sink

    def _precheck(
        self, request: PrecheckRequest, *, evidence_sink: dict | None = None
    ) -> PrecheckResponse:
        started = time.perf_counter_ns()
        payload = self._request_payload(request)
        digest = payload_digest(payload)

        stored = self.repository.get_request(
            request.request_id
        ) or self.repository.get_request_by_event(request.event_id)
        if stored is not None:
            if stored.payload_digest != digest:
                raise DuplicateConflictError(
                    "request retry conflicts with stored payload"
                )
            response = json.loads(stored.response_json)
            response["idempotent_replay"] = True
            if evidence_sink is not None:
                evidence_sink.update(json.loads(stored.evidence_json))
            return PrecheckResponse.model_validate(response)
        if self.repository.get_event(request.event_id):
            raise DuplicateConflictError(
                "event ID is already used by another transition"
            )

        event = LifecycleEvent.model_validate(payload)
        snapshot = self.engine.snapshot(event)
        if evidence_sink is not None:
            evidence_sink.update(safe_evidence(snapshot))

        risk_score = self.registry.model.score(snapshot)
        self.model_score_calls += 1
        moment = _utc(request.timestamp)
        decision = self.policy.decide(
            snapshot=snapshot,
            risk_score=risk_score,
            timestamp=moment,
            campaign_active=bool(request.campaign_active),
        )

        committed = self.engine.record_request(
            event, blocked=decision.action == "block"
        )
        if any(committed[name] != snapshot[name] for name in MODEL_FEATURES_V2):
            raise RuntimeStateError("feature snapshot changed during the decision")

        latency_ms = (time.perf_counter_ns() - started) / 1_000_000
        response = PrecheckResponse(
            request_id=request.request_id,
            event_id=request.event_id,
            decision=decision.action,
            risk_score=risk_score,
            rule_score=decision.rule_score,
            reason_codes=list(decision.reason_codes),
            decision_basis=self.registry.policy_mode,
            model_status=self.registry.model.status,
            device_state_version=int(committed["state_version"]),
            idempotent_replay=False,
            processed_at=datetime.now(UTC),
            latency_ms=latency_ms,
            block_expires_at=decision.block_expires_at,
        )
        record = StoredRequest(
            request_id=request.request_id,
            event_id=request.event_id,
            merchant_hash=payload["merchant_id"],
            customer_hash=payload.get("customer_id"),
            device_hash=event.device_id,
            session_hash=event.session_id,
            ip_hash=event.ip_fingerprint,
            timestamp=event.timestamp.isoformat(),
            event_sequence=event.event_sequence,
            payload_digest=digest,
            payload_json=json.dumps(payload, sort_keys=True),
            decision=decision.action,
            risk_score=risk_score,
            rule_score=decision.rule_score,
            reason_codes_json=json.dumps(list(decision.reason_codes)),
            state_version=int(committed["state_version"]),
            response_json=response.model_dump_json(),
            latency_ms=latency_ms,
            evidence_json=json.dumps(safe_evidence(snapshot)),
        )
        try:
            self.repository.save_request(record)
        except Exception:
            self.rebuild_from_persistence()
            raise
        LOGGER.info(
            "precheck decision=%s rule_score=%s basis=%s state_version=%s",
            decision.action,
            decision.rule_score,
            self.registry.policy_mode,
            record.state_version,
        )
        return response

    # -- outcome / checkout -------------------------------------------

    async def outcome(self, request: OutcomeRequest) -> TransitionResponse:
        async with self.lock:
            return self._transition(request, "authorization_outcome")

    async def checkout(self, request: CheckoutRequest) -> TransitionResponse:
        async with self.lock:
            return self._transition(request, "checkout_completion")

    async def trusted_gateway_outcome(
        self,
        *,
        request_id: str,
        event_id: str,
        timestamp: datetime,
        authorization_result: str,
        failure_reason: str | None = None,
    ) -> TransitionResponse:
        """Record an already-authenticated gateway result using stored hashes.

        Webhooks do not contain the browser's raw device/session identifiers,
        and protected identifiers are intentionally irreversible. This path is
        therefore available only to the server-side gateway service.
        """
        async with self.lock:
            stored = self.repository.get_request(request_id)
            if stored is None:
                raise InvalidLifecycleTransition("request does not exist")
            payload = {
                "event_id": event_id,
                "request_id": request_id,
                "event_sequence": stored.event_sequence + 1,
                "timestamp": _utc(timestamp).isoformat(),
                "event_type": "authorization_outcome",
                "device_id": stored.device_hash,
                "session_id": stored.session_hash,
                "authorization_result": authorization_result,
            }
            if failure_reason is not None:
                payload["failure_reason"] = failure_reason
            return self._transition_payload(payload, "authorization_outcome")

    async def trusted_gateway_checkout(
        self, *, request_id: str, event_id: str, timestamp: datetime
    ) -> TransitionResponse:
        async with self.lock:
            stored = self.repository.get_request(request_id)
            if stored is None:
                raise InvalidLifecycleTransition("request does not exist")
            payload = {
                "event_id": event_id,
                "request_id": request_id,
                "event_sequence": stored.event_sequence + 2,
                "timestamp": _utc(timestamp).isoformat(),
                "event_type": "checkout_completion",
                "device_id": stored.device_hash,
                "session_id": stored.session_hash,
            }
            return self._transition_payload(payload, "checkout_completion")

    def _transition(
        self, request: OutcomeRequest | CheckoutRequest, event_type: str
    ) -> TransitionResponse:
        payload = (
            self._outcome_payload(request)
            if event_type == "authorization_outcome"
            else self._checkout_payload(request)
        )
        return self._transition_payload(payload, event_type)

    def _transition_payload(self, payload: dict, event_type: str) -> TransitionResponse:
        request_id = str(payload["request_id"])
        event_id = str(payload["event_id"])
        digest = payload_digest(payload)
        existing = self.repository.get_event(
            event_id
        ) or self.repository.get_event_for_request(request_id, event_type)
        if existing is not None:
            if existing.payload_digest != digest:
                raise DuplicateConflictError(
                    "lifecycle retry conflicts with stored payload"
                )
            return TransitionResponse(
                event_id=event_id,
                request_id=request_id,
                accepted=True,
                idempotent_replay=True,
                device_state_version=existing.state_version,
                processed_at=datetime.now(UTC),
            )
        if self.repository.get_request_by_event(event_id):
            raise DuplicateConflictError("event ID is already used by a request")

        stored_request = self.repository.get_request(request_id)
        if stored_request is None:
            raise InvalidLifecycleTransition("request does not exist")
        if (
            stored_request.device_hash != payload["device_id"]
            or stored_request.session_hash != payload["session_id"]
        ):
            raise InvalidLifecycleTransition("transition crosses device or session")
        if stored_request.decision == "block":
            raise InvalidLifecycleTransition(
                "a blocked request cannot receive an outcome or checkout"
            )

        event = LifecycleEvent.model_validate(payload)
        try:
            if event_type == "authorization_outcome":
                self.engine.record_outcome(event)
            else:
                self.engine.record_checkout(event)
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

    # -- rebuild / reads --------------------------------------------

    def rebuild_from_persistence(self) -> None:
        self.engine = FeatureEngineV2()
        self.policy = RiskPolicyV2(self.registry.policy)
        rows = [
            (row.timestamp, row.event_sequence, "request", row)
            for row in self.repository.requests_in_order()
        ] + [
            (row.timestamp, row.event_sequence, "event", row)
            for row in self.repository.events_in_order()
        ]
        for _timestamp, _sequence, kind, row in sorted(
            rows, key=lambda r: (r[0], r[1])
        ):
            event = LifecycleEvent.model_validate(json.loads(row.payload_json))
            if kind == "request":
                snapshot = self.engine.snapshot(event)
                decision = self.policy.decide(
                    snapshot=snapshot,
                    risk_score=row.risk_score,
                    timestamp=event.timestamp,
                    campaign_active=bool(
                        json.loads(row.payload_json).get("campaign_active", False)
                    ),
                )
                if decision.action != row.decision:
                    raise RuntimeStateError("a persisted decision does not reproduce")
                committed = self.engine.record_request(
                    event, blocked=row.decision == "block"
                )
                if int(committed["state_version"]) != row.state_version:
                    raise RuntimeStateError(
                        "a persisted state version does not reproduce"
                    )
            elif row.event_type == "authorization_outcome":
                self.engine.record_outcome(event)
            else:
                self.engine.record_checkout(event)
            if self.engine.devices[event.device_id].state_version != row.state_version:
                raise RuntimeStateError("a persisted lifecycle state version mismatch")

    def decisions(self, limit: int) -> list[dict]:
        return self.repository.decisions(limit)

    def timeline(self, raw_device_id: str) -> list[dict]:
        return self.repository.device_timeline(
            self.protector.protect("device", raw_device_id)
        )

    def close(self) -> None:
        self.repository.close()
