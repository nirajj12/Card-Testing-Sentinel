"""Unit tests for the fail-closed runtime compatibility preflight.

These tests exercise card_testing_sentinel.modeling.compatibility directly,
against a synthetic model-metadata file, so they do not depend on the real
frozen artifact's exact recorded versions and stay correct as long as the
*running* interpreter is whatever CI/the dev environment actually installed.
"""

from __future__ import annotations

import json
import warnings

import pytest
from sklearn.exceptions import InconsistentVersionWarning

from card_testing_sentinel.domain.exceptions import ArtifactIntegrityError
from card_testing_sentinel.modeling import compatibility


def _write_metadata(root, runtime: dict) -> None:
    model_dir = root / "artifacts" / "model"
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "metadata.json").write_text(json.dumps({"runtime": runtime}))


def _matching_runtime() -> dict:
    actual = compatibility.actual_versions()
    return {
        "python": f"{actual['python']}.7 (main) [Clang]",
        "scikit_learn": actual["scikit_learn"],
        "numpy": actual["numpy"],
        "scipy": actual["scipy"],
        "joblib": actual["joblib"],
    }


def test_compatible_runtime_reports_no_mismatches(tmp_path):
    _write_metadata(tmp_path, _matching_runtime())

    report = compatibility.check_runtime_compatibility(tmp_path)

    assert report.compatible is True
    assert report.mismatches == []
    assert (
        report.expected["scikit_learn"]
        == compatibility.actual_versions()["scikit_learn"]
    )


def test_require_compatible_runtime_passes_silently_when_aligned(tmp_path):
    _write_metadata(tmp_path, _matching_runtime())

    report = compatibility.require_compatible_runtime(tmp_path)

    assert report.compatible is True


def test_incompatible_scikit_learn_is_reported_and_fails_closed(tmp_path):
    runtime = _matching_runtime()
    runtime["scikit_learn"] = "1.9.0"
    _write_metadata(tmp_path, runtime)

    report = compatibility.check_runtime_compatibility(tmp_path)
    assert report.compatible is False
    assert {
        "package": "scikit_learn",
        "expected": "1.9.0",
        "actual": compatibility.actual_versions()["scikit_learn"],
    } in report.mismatches

    with pytest.raises(compatibility.RuntimeCompatibilityError) as excinfo:
        compatibility.require_compatible_runtime(tmp_path)
    assert "scikit_learn" in str(excinfo.value)
    assert "1.9.0" in str(excinfo.value)
    assert excinfo.value.report.compatible is False


def test_incompatible_supporting_serialization_dependency_is_reported(tmp_path):
    """numpy is not scikit-learn itself but its version still governs how
    the pickled estimator's array state is reconstructed -- a mismatch
    here must fail closed exactly like a scikit-learn mismatch."""
    runtime = _matching_runtime()
    runtime["numpy"] = "0.0.1"
    _write_metadata(tmp_path, runtime)

    report = compatibility.check_runtime_compatibility(tmp_path)
    assert report.compatible is False
    assert any(item["package"] == "numpy" for item in report.mismatches)

    with pytest.raises(compatibility.RuntimeCompatibilityError):
        compatibility.require_compatible_runtime(tmp_path)


def test_python_patch_version_difference_is_not_a_mismatch(tmp_path):
    """Patch releases within the same 3.11.x line are expected to
    interoperate; only major.minor is compared."""
    runtime = _matching_runtime()
    runtime["python"] = runtime["python"].replace(
        compatibility.actual_versions()["python"],
        f"{compatibility.actual_versions()['python']}.999",
    )
    _write_metadata(tmp_path, runtime)

    report = compatibility.check_runtime_compatibility(tmp_path)

    assert report.compatible is True


def test_missing_recorded_runtime_versions_fails_closed(tmp_path):
    _write_metadata(tmp_path, {"python": "3.11.15"})

    with pytest.raises(ArtifactIntegrityError):
        compatibility.check_runtime_compatibility(tmp_path)


def test_load_model_artifact_strict_escalates_inconsistent_version_warning(
    tmp_path, monkeypatch
):
    """Even if the coarse version check somehow passes, an
    InconsistentVersionWarning raised while unpickling must still fail
    closed rather than pass through as a warning."""
    _write_metadata(tmp_path, _matching_runtime())

    def _fake_load(_path):
        warnings.warn(
            InconsistentVersionWarning(
                estimator_name="LogisticRegression",
                current_sklearn_version="1.9.0",
                original_sklearn_version="1.6.1",
            ),
            stacklevel=2,
        )
        return object()

    monkeypatch.setattr(compatibility.joblib, "load", _fake_load)

    with pytest.raises(compatibility.RuntimeCompatibilityError) as excinfo:
        compatibility.load_model_artifact_strict(tmp_path / "model.joblib", tmp_path)
    assert "InconsistentVersionWarning" in str(excinfo.value)


def test_load_model_artifact_strict_does_not_suppress_other_warnings(
    tmp_path, monkeypatch
):
    """The preflight must only escalate InconsistentVersionWarning -- it
    must never globally suppress other warnings raised during load."""

    def _fake_load(_path):
        warnings.warn(UserWarning("unrelated warning"), stacklevel=2)
        return "loaded"

    monkeypatch.setattr(compatibility.joblib, "load", _fake_load)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = compatibility.load_model_artifact_strict(
            tmp_path / "model.joblib", tmp_path
        )

    assert result == "loaded"
    assert any(issubclass(w.category, UserWarning) for w in caught)
