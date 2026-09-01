"""Razorpay Test Mode boundary for Standard Checkout."""

from fastapi import APIRouter

from card_testing_sentinel.api.contracts import (
    RazorpayOrderRequest,
    RazorpayPaymentVerificationRequest,
)
from card_testing_sentinel.api.dependencies import RuntimeDependency
from card_testing_sentinel.domain.exceptions import PaymentGatewayConfigurationError

router = APIRouter(prefix="/api/razorpay")


def _service(runtime):
    if not runtime.ready or runtime.razorpay is None:
        raise PaymentGatewayConfigurationError("Razorpay Test Mode is unavailable")
    return runtime.razorpay


@router.get("/status")
def status(runtime: RuntimeDependency) -> dict:
    if not runtime.ready or runtime.razorpay is None:
        return {"configured": False, "mode": "unavailable"}
    return runtime.razorpay.public_status


@router.post("/orders")
async def create_order(
    payload: RazorpayOrderRequest, runtime: RuntimeDependency
) -> dict:
    return await _service(runtime).create_order(
        request_id=payload.sentinel_request_id,
        device_id=payload.device_id,
        session_id=payload.session_id,
    )


@router.post("/payments/verify")
async def verify_payment(
    payload: RazorpayPaymentVerificationRequest, runtime: RuntimeDependency
) -> dict:
    return await _service(runtime).verify_payment(
        request_id=payload.sentinel_request_id,
        device_id=payload.device_id,
        session_id=payload.session_id,
        razorpay_order_id=payload.razorpay_order_id,
        razorpay_payment_id=payload.razorpay_payment_id,
        razorpay_signature=payload.razorpay_signature,
    )


@router.post("/orders/checkout-opened")
async def checkout_opened(
    payload: RazorpayOrderRequest, runtime: RuntimeDependency
) -> dict:
    return await _service(runtime).mark_checkout_opened(
        request_id=payload.sentinel_request_id,
        device_id=payload.device_id,
        session_id=payload.session_id,
    )
