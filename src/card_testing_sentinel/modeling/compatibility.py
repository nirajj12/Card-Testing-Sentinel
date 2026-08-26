"""Fail-closed runtime dependency compatibility preflight.

The frozen model artifact was serialized once, with one exact toolchain
(Python, scikit-learn, numpy, scipy, joblib). Loading that pickle under a
different toolchain can silently change predictions, or raise a confusing
error deep inside scoring well after startup looked healthy. This module
compares the *running* interpreter and package versions against the
canonical versions recorded in the frozen model's own metadata, and fails
closed -- refusing to even attempt ``joblib.load`` -- on any mismatch,
instead of letting scikit-learn's ``InconsistentVersionWarning`` pass by
unnoticed.

``require_compatible_runtime`` must run, and must succeed, before the model
artifact is ever opened.
"""

from __future__ import annotations

import sys
import warnings
from dataclasses import dataclass, field
from pathlib import Path

import joblib
import numpy
import scipy
import sklearn

from card_testing_sentinel.common.integrity import load_json
from card_testing_sentinel.domain.exceptions import ArtifactIntegrityError

#: packages whose *exact* installed version must match the version recorded
#: for the frozen model release before the model may be loaded.
CHECKED_PACKAGES: tuple[str, ...] = ("scikit_learn", "numpy", "scipy", "joblib")

_INSTALLED_VERSIONS = {
    "scikit_learn": sklearn.__version__,
    "numpy": numpy.__version__,
    "scipy": scipy.__version__,
    "joblib": joblib.__version__,
}


@dataclass(frozen=True)
class CompatibilityReport:
    """Expected-vs-actual runtime versions, safe to surface verbatim over
    the API (no paths, no secrets -- only package/interpreter versions)."""

    compatible: bool
    expected: dict[str, str]
    actual: dict[str, str]
    mismatches: list[dict[str, str]] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "compatible": self.compatible,
            "expected": self.expected,
            "actual": self.actual,
            "mismatches": self.mismatches,
        }


class RuntimeCompatibilityError(ArtifactIntegrityError):
    """Raised when the running interpreter/package versions do not match
    the frozen model's recorded serialization environment. The model is
    never loaded when this is raised."""

    error_code = "runtime_compatibility_error"

    def __init__(self, message: str, report: CompatibilityReport):
        super().__init__(message)
        self.report = report


def _python_minor(raw_version: str) -> str:
    # Model metadata stores the full interpreter banner, e.g.
    # "3.11.15 (main, Jun 11 2026, 15:14:57) [Clang 20.1.8 ]". Only the
    # major.minor line matters for pickle/ABI compatibility -- patch
    # releases of the same minor are expected to interoperate.
    token = raw_version.split()[0] if raw_version else ""
    parts = token.split(".")
    return ".".join(parts[:2]) if len(parts) >= 2 else token


def expected_versions(root: Path) -> dict[str, str]:
    """The canonical package/interpreter versions the frozen model was
    serialized under, read from the model's own metadata -- the same
    metadata file whose hash is pinned in the release manifest, so this
    cannot silently drift from what actually shipped."""
    metadata = load_json(root / "artifacts/model/metadata.json")
    runtime = metadata.get("runtime", {})
    missing = sorted(name for name in CHECKED_PACKAGES if name not in runtime)
    if missing:
        raise ArtifactIntegrityError(
            f"model metadata is missing recorded runtime versions: {missing}"
        )
    expected = {name: str(runtime[name]) for name in CHECKED_PACKAGES}
    expected["python"] = _python_minor(str(runtime.get("python", "")))
    return expected


def actual_versions() -> dict[str, str]:
    """The package/interpreter versions actually running right now."""
    actual = dict(_INSTALLED_VERSIONS)
    actual["python"] = ".".join(str(part) for part in sys.version_info[:2])
    return actual


def check_runtime_compatibility(root: Path) -> CompatibilityReport:
    """Build a compatibility report without raising. Callers that must
    fail closed should use :func:`require_compatible_runtime` instead."""
    expected = expected_versions(root)
    actual = actual_versions()
    mismatches = [
        {
            "package": name,
            "expected": expected[name],
            "actual": actual.get(name, "not installed"),
        }
        for name in expected
        if actual.get(name) != expected[name]
    ]
    return CompatibilityReport(
        compatible=not mismatches,
        expected=expected,
        actual=actual,
        mismatches=mismatches,
    )


def require_compatible_runtime(root: Path) -> CompatibilityReport:
    """Fail-closed preflight. Must be called, and must succeed, before
    ``joblib.load`` is ever invoked on the model artifact."""
    report = check_runtime_compatibility(root)
    if not report.compatible:
        details = "; ".join(
            f"{item['package']} expected {item['expected']}, found {item['actual']}"
            for item in report.mismatches
        )
        raise RuntimeCompatibilityError(
            "runtime is incompatible with the frozen model's serialization "
            f"environment: {details}",
            report,
        )
    return report


def load_model_artifact_strict(path: Path, root: Path):
    """``joblib.load`` the frozen model artifact, promoting scikit-learn's
    ``InconsistentVersionWarning`` into a hard failure instead of a silent
    warning. This is defense in depth behind :func:`require_compatible_runtime`
    for any version-skew the coarse package-version check does not catch
    (for example a compatible release that still trips scikit-learn's own
    pickle-version guard). No other warning category is touched or
    suppressed here. ``root`` is only used to render expected-vs-actual
    versions in the error; it is not re-checked here."""
    from sklearn.exceptions import InconsistentVersionWarning

    with warnings.catch_warnings():
        warnings.simplefilter("error", category=InconsistentVersionWarning)
        try:
            return joblib.load(path)
        except InconsistentVersionWarning as error:
            try:
                expected = expected_versions(root)
            except Exception:
                expected = {}
            raise RuntimeCompatibilityError(
                "model artifact unpickling raised scikit-learn's "
                f"InconsistentVersionWarning: {error}",
                CompatibilityReport(
                    compatible=False,
                    expected=expected,
                    actual=actual_versions(),
                    mismatches=[
                        {
                            "package": "scikit_learn",
                            "expected": "matches frozen model metadata",
                            "actual": str(error),
                        }
                    ],
                ),
            ) from error
