"""Identifier normalization and one-way HMAC protection."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
from dataclasses import dataclass

from card_testing_sentinel.v2.phase4.exceptions import RuntimeStateError


@dataclass(frozen=True)
class IdentifierProtector:
    secret: bytes

    @classmethod
    def from_secret(cls, value: str | None) -> IdentifierProtector:
        if value is None or len(value.strip()) < 16:
            raise RuntimeStateError(
                "CTS_HMAC_SECRET must contain at least 16 characters"
            )
        return cls(value.encode())

    def protect(self, kind: str, value: str) -> str:
        normalized = value.strip().lower()
        digest = hmac.new(
            self.secret,
            f"{kind}:{normalized}".encode(),
            hashlib.sha256,
        ).hexdigest()
        return f"hmac_{kind}_{digest}"

    def protect_ip(self, value: str) -> str:
        try:
            normalized = ipaddress.ip_address(value.strip()).compressed
        except ValueError:
            normalized = value.strip().lower()
            if not normalized or len(normalized) > 200:
                raise ValueError("invalid IP reference") from None
        return self.protect("ip", normalized)


def payload_digest(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()
