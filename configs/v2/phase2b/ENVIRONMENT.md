# Phase 2B canonical environment

## Canonical statement

The locked CPython 3.11.15 environment described below —
`$HOME/envs/card-testing-sentinel-v2b`, a plain `venv` with every dependency
pinned to an exact version in `configs/v2/phase2b/requirements-lock.txt` —
**is the canonical, reproducible automation environment for Phase 2B.**

- Conda is an **optional local convenience wrapper** around this same
  interpreter and the same dependency lock. A developer who prefers Conda
  may run `conda create -n card-testing-sentinel-v2b python=3.11.15` and
  `pip install -r configs/v2/phase2b/requirements-lock.txt` inside it; the
  result is the same interpreter version and the same resolved package set,
  not a different environment.
- Reproducibility here depends on **the interpreter version and the locked
  dependency versions**, not on which environment-manager brand created the
  virtualenv. Conda, `venv`, `uv venv`, and `virtualenv` are equally valid
  mechanisms for materializing the same lock; none of them is a
  correctness requirement in itself.
- The old Python 3.13.2 serialized V2 model (the historical, blocked Phase 2
  artifact) is **not being reused or certified as a Phase 2B artifact under
  this environment.** Gate E/Gate 7's separate-process serialization proof
  demonstrates only that a *fresh* model trained inside this canonical
  Python 3.11.15 environment survives a save/load round trip with identical
  predictions — it does not, and is not meant to, bless the old artifact.
- **New Phase 2B models will be trained and serialized only inside this
  canonical Python 3.11.15 environment** (or a Conda wrapper around the
  identical lock, per the point above) — never under the old Python 3.13
  runtime, and never under the repository's own ad hoc `.venv/`.

Further Conda installation, download, or debugging work is out of scope for
this and future corrective passes: the device bridge this project's
automated work runs in is an isolated Linux VM, architecturally separate
from any interactive machine where Conda may already work, and its bundled
Conda-bootstrap binary (`micromamba`) segfaults on this VM regardless of
network conditions (reproduced twice, `exit 139`/SIGSEGV, independent of any
download). This is treated as a permanent, accepted constraint of this
automation environment, not an open problem.

## Recreation command

```
# Using the canonical venv directly (what automation in this environment does):
python3.11 -m venv card-testing-sentinel-v2b
card-testing-sentinel-v2b/bin/pip install --no-deps -r configs/v2/phase2b/requirements-lock.txt
card-testing-sentinel-v2b/bin/pip install --no-deps -e .

# Equivalent, for a developer who prefers Conda on their own machine:
conda create -n card-testing-sentinel-v2b python=3.11.15 -y
conda run -n card-testing-sentinel-v2b python -m pip install --no-deps -r configs/v2/phase2b/requirements-lock.txt
conda run -n card-testing-sentinel-v2b python -m pip install --no-deps -e .
```

Clean-environment reproduction check (either path):

```
python -c "import numpy, pandas, sklearn, joblib, fastapi, starlette, httpx, uvicorn, jinja2, yaml, pytest, ruff, mlflow; print('ok')"
pytest -q
ruff format --check .
ruff check .
```

## How the canonical venv was actually built

On this arm64 Mac, `$HOME/envs/card-testing-sentinel-v2b` was created with the
CPython 3.11.15 interpreter already installed at
`/opt/anaconda3/envs/card-testing-sentinel/bin/python`. The project was
installed editable with `--no-deps`, followed by the exact lock with
`--no-deps`; all locked runtime imports and the complete test suite passed.

The explicit `--no-deps` is necessary because the project metadata names the
full `mlflow` distribution while the lock intentionally installs
`mlflow-skinny`. Both expose the required `mlflow` import namespace, but pip's
distribution-level `pip check` therefore reports that `mlflow` is missing.
This packaging-metadata mismatch is disclosed rather than hidden or resolved
by changing historical project metadata during the training-freeze phase.

## Exact resolved versions (from a successful install, see requirements-lock.txt)

Python 3.11.15; numpy 1.26.4; pandas 2.2.3; scikit-learn 1.6.1; scipy 1.14.1;
joblib 1.4.2; PyYAML 6.0.2; pydantic 2.9.2 (+ pydantic_core 2.23.4); FastAPI
0.115.0; Starlette 0.38.6; **httpx 0.27.2 (the standard package — not a
package named "httpx2")**; uvicorn 0.30.6; Jinja2 3.1.4; matplotlib 3.9.2;
ruff 0.8.4; pytest 8.3.3; pytest-cov 5.0.0; coverage 7.6.1;
**mlflow-skinny 3.15.1** (an official trimmed distribution exposing the same
`mlflow` import namespace, with no server/UI extras needed for this project's
tracking calls, but not satisfying pip's distribution-name check for the
`mlflow>=3.0,<4` project requirement) plus its full
resolved dependency closure (`databricks-sdk`, `opentelemetry-{api,sdk,proto}`,
`gitpython`, `cryptography`, `google-auth`, `protobuf`, `requests`,
`sqlparse`, `cachetools`, `cloudpickle`, `python-dotenv`, and their own
transitive dependencies — 24 packages in total).

`numpy` was deliberately pinned to 1.26.4, matching the exact version
recorded in `artifacts/v2/training/training_freeze.json.runtime` for the
original (Python 3.13.2) V2 model, rather than a newer numpy — a first
attempt with numpy 2.4.6 produced
`UserWarning: A NumPy version >=1.23.5 and <2.3.0 is required for this
version of SciPy (detected version 2.4.6)` when importing
`sklearn.utils._param_validation`, which is a real, reproduced incompatibility,
not a hypothetical one. `scikit-learn` was pinned to 1.6.1 and `joblib` to
1.4.2 for the same reason: matching the original training runtime's recorded
versions maximizes comparability between whatever Phase 2B trains next and
the historical (unreproducible) Phase 2 result.

## MLflow

`mlflow-skinny==3.15.1` is installed and verified: `import mlflow` succeeds,
and a local-file-store smoke test (create experiment, start run, log one
param and one metric, read both back) passes under
`MLFLOW_ALLOW_FILE_STORE=true` (mlflow 3.x's documented opt-out of its new
default sqlite-only tracking backend), entirely under a temporary directory.
`tests/integration/test_baseline_training.py` — the one test file that
imports a module with a module-level `import mlflow` — passes for real
against this installation.
