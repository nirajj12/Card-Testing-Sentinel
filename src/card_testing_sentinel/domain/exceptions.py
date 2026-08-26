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
