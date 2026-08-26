"""Safe Phase 4 application errors."""


class Phase4Error(Exception):
    status_code = 500
    error_code = "phase4_error"


class ArtifactIntegrityError(Phase4Error):
    status_code = 503
    error_code = "artifact_integrity_error"


class DuplicateConflictError(Phase4Error):
    status_code = 409
    error_code = "duplicate_conflict"


class CausalOrderingError(Phase4Error):
    status_code = 409
    error_code = "causal_ordering_error"


class InvalidLifecycleTransition(Phase4Error):
    status_code = 409
    error_code = "invalid_lifecycle_transition"


class RuntimeStateError(Phase4Error):
    status_code = 503
    error_code = "runtime_state_error"
