"""Exceptions intentionally exposed by Card-Testing Sentinel."""


class SentinelError(Exception):
    """Base exception for expected project failures."""


class ConfigurationError(SentinelError):
    """Raised when application configuration cannot be loaded or validated."""


class DataValidationError(SentinelError):
    """Raised when frozen data violates a required dataset contract."""


class ModelTrainingError(SentinelError):
    """Raised when an offline modeling or evaluation guardrail fails."""


class PolicyEvaluationError(SentinelError):
    """Raised when policy selection or final-evaluation safeguards fail."""
