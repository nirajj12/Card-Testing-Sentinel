from datetime import UTC, datetime, timedelta


def precheck_payload(
    index: int = 1,
    *,
    base: datetime | None = None,
    merchant: str = "merchant-demo",
    device: str = "device-demo",
    session: str = "session-demo",
    ip: str = "198.51.100.10",
    amount: float = 2.0,
) -> dict:
    origin = base or datetime(2030, 1, 1, tzinfo=UTC)
    return {
        "request_id": f"request-{index}",
        "event_id": f"precheck-{index}",
        "merchant_id": merchant,
        "device_id": device,
        "session_id": session,
        "ip_reference": ip,
        "amount": amount,
        "currency": "USD",
        "campaign_active": False,
        "timestamp": (origin + timedelta(seconds=index * 10)).isoformat(),
        "event_sequence": index * 3,
    }


def outcome_payload(
    index: int = 1,
    *,
    base: datetime | None = None,
    approved: bool = False,
    with_card: bool = False,
) -> dict:
    origin = base or datetime(2030, 1, 1, tzinfo=UTC)
    payload = {
        "event_id": f"outcome-{index}",
        "request_id": f"request-{index}",
        "device_id": "device-demo",
        "session_id": "session-demo",
        "timestamp": (origin + timedelta(seconds=index * 10 + 1)).isoformat(),
        "event_sequence": index * 3 + 1,
        "authorization_result": "approved" if approved else "declined",
    }
    if not approved:
        payload["failure_reason"] = "generic_decline"
    if with_card:
        payload["payment_method"] = "card"
        payload["card_last4"] = f"{1000 + index}"
        payload["card_network"] = "visa"
    return payload
