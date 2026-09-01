"""Safe application errors with stable HTTP mappings."""


class ApplicationError(Exception):
    status_code = 500
    error_code = "application_error"


class ArtifactIntegrityError(ApplicationError):
    status_code = 503
    error_code = "artifact_integrity_error"


class DuplicateConflictError(ApplicationError):
    status_code = 409
    error_code = "duplicate_conflict"


class CausalOrderingError(ApplicationError):
    status_code = 409
    error_code = "causal_ordering_error"


class InvalidLifecycleTransition(ApplicationError):
    status_code = 409
    error_code = "invalid_lifecycle_transition"


class RuntimeStateError(ApplicationError):
    status_code = 503
    error_code = "runtime_state_error"


class PaymentGatewayConfigurationError(ApplicationError):
    status_code = 503
    error_code = "payment_gateway_unavailable"


class PaymentOrderNotAllowed(ApplicationError):
    status_code = 409
    error_code = "payment_order_not_allowed"


class PaymentGatewayError(ApplicationError):
    status_code = 502
    error_code = "payment_gateway_error"


class PaymentSignatureError(ApplicationError):
    status_code = 400
    error_code = "invalid_payment_signature"


class PaymentWebhookPayloadError(ApplicationError):
    status_code = 400
    error_code = "invalid_webhook_payload"
