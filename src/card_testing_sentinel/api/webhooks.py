"""Authenticated Razorpay webhook ingress."""

from fastapi import APIRouter, Request

from card_testing_sentinel.api.dependencies import RuntimeDependency
from card_testing_sentinel.domain.exceptions import (
    PaymentGatewayConfigurationError,
    PaymentWebhookPayloadError,
)

router = APIRouter(prefix="/api/webhooks")


@router.post("/razorpay")
async def razorpay_webhook(request: Request, runtime: RuntimeDependency) -> dict:
    if not runtime.ready or runtime.razorpay is None:
        raise PaymentGatewayConfigurationError("Razorpay webhook is unavailable")
    signature = request.headers.get("X-Razorpay-Signature", "")
    delivery_id = request.headers.get("x-razorpay-event-id", "").strip()
    if not delivery_id:
        raise PaymentWebhookPayloadError("x-razorpay-event-id is required")
    raw_body = await request.body()
    return await runtime.razorpay.process_webhook(
        raw_body=raw_body,
        signature=signature,
        delivery_id=delivery_id,
    )
