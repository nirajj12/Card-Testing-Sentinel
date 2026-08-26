from datetime import UTC, datetime, timedelta


def precheck_payload(
    index: int = 1,
    *,
    base: datetime | None = None,
    device: str = "device-demo",
    session: str = "session-demo",
    card: str = "gateway-card-demo",
    ip: str = "198.51.100.10",
) -> dict:
    origin = base or datetime(2030, 1, 1, tzinfo=UTC)
    return {
        "request_id": f"request-{index}",
        "event_id": f"precheck-{index}",
        "device_id": device,
        "session_id": session,
        "card_reference": card,
        "card_bin": "410000",
        "ip_reference": ip,
        "amount": 2.0,
        "currency": "USD",
        "timestamp": (origin + timedelta(seconds=index * 10)).isoformat(),
        "event_sequence": index * 3,
        "campaign_active": False,
    }


def outcome_payload(index: int = 1, *, base: datetime | None = None) -> dict:
    origin = base or datetime(2030, 1, 1, tzinfo=UTC)
    return {
        "event_id": f"outcome-{index}",
        "request_id": f"request-{index}",
        "device_id": "device-demo",
        "session_id": "session-demo",
        "timestamp": (origin + timedelta(seconds=index * 10 + 1)).isoformat(),
        "event_sequence": index * 3 + 1,
        "authorization_result": "declined",
        "decline_reason": "generic_decline",
    }
