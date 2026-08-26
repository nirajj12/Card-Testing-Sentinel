# Final hardening repository inventory

Captured on 2026-08-26 before the final hardening cleanup. This inventory classifies every current file through exhaustive path families; individual dependency, cache, and bytecode members are intentionally classified as complete families rather than repeated thousands of times.

The repository is on `submission-clean` with rollback branch `checkpoint/full-system-20260826` and rollback tag `pre-submission-cleanup-20260826`, all based on commit `d56927eabdd83c9d01eb66bf413ad56663073651`. The extensive Git deletions already present belong to the earlier classified submission cleanup and are covered by `reports/submission_cleanup_inventory.md`.

| Complete current path or path family | Classification | Final-hardening disposition |
|---|---|---|
| `src/card_testing_sentinel/api/**`, `app.py`, `domain/**`, `features/**`, `modeling/**`, `persistence/**`, `policy/**`, `security/**`, `services/**`, `web/**` excluding caches | Required source code | Retain. This is the production and development code. |
| `configs/app.yaml`, `configs/features.yaml`, `configs/policy.yaml`, `configs/training.yaml` | Required configuration | Retain byte-for-byte where protected; no policy/feature changes. |
| `artifacts/model/risk_model.joblib`, `feature_contract.json`, `metadata.json`, `artifacts/policy/operational_policy.json` | Frozen runtime artifact | Retain byte-for-byte and re-verify hashes. |
| `artifacts/evaluation/blind_metrics.json`, `blind_device_summary.csv`, `blind_event_decisions.csv` | Evaluation evidence | Retain byte-for-byte. Do not rescore; live startup and benchmarks must not open row-level CSVs. |
| `artifacts/release_manifest.json`, `artifacts/release_manifest.sha256` | Frozen runtime artifact / reproducibility evidence | Retain byte-for-byte. |
| `tests/fixtures/golden/live_parity.json` | Test fixture | Retain and hash independently. It contains no blind rows. |
| `tests/fixtures/scenarios/plans.json` | Test fixture | Retain. Deterministic raw scenario input shapes only. |
| `tests/frontend/**`, `tests/integration/**`, `tests/unit/**`, `tests/conftest.py`, `tests/helpers.py` excluding caches | Test fixture / test suite | Retain. |
| `pipelines/**` | Development-only reproducibility source | Retain. These regenerate development-only evidence and do not replace blind evidence. |
| `scripts/run_app.py`, `scripts/verify_release.py`, `scripts/benchmark.py` | Required source code / reproducibility script | Retain. |
| `README.md`, `docs/*.md`, `docs/screenshots/*.png`, `LICENSE` | Documentation | Retain. Screenshots are required submission evidence. |
| `reports/final_hardening_baseline.md`, `reports/final_hardening_inventory.md`, final benchmark/security reports | Generated report / submission evidence | Retain. |
| `reports/submission_cleanup_inventory.md`, `reports/submission_cleanup_report.md` | Generated report / historical cleanup evidence | Retain; they explain the already-dirty worktree and prior classified removal. |
| `pyproject.toml`, `requirements-runtime.lock`, `requirements-dev.lock`, `requirements-lock.txt`, `environment.yml` | Required configuration / exact dependency lock | Retain. |
| `Dockerfile`, `.dockerignore`, `.github/workflows/ci.yml`, `.env.example` | Required configuration / deployment preparation | Retain. `.env.example` contains a placeholder, not a secret. |
| `package.json`, `package-lock.json`, `.nvmrc` | Development/test dependency configuration | Retain. |
| `.gitignore` | Required configuration | Retain and harden before cleanup verification. |
| `.venv/**` | Development-only local environment | Do not package; ignored. Leave on the workstation because it predates this cleanup and is outside Git. |
| `node_modules/**` | Development-only dependency installation | Do not package; ignore. Leave locally unless the user later requests removal. |
| `**/__pycache__/**`, `*.pyc` | Cache | Disposable; remove after this inventory. |
| `.pytest_cache/**`, `.ruff_cache/**`, `.coverage`, `.coverage.*`, `htmlcov/**` | Cache / generated report | Disposable; remove after this inventory. |
| `data/runtime/live_state.sqlite3` and any `*.db`, `*.sqlite`, `*.sqlite3`, `*-wal`, `*-shm` | Runtime database / temporary state | Disposable from the repository; remove after this inventory. Never package. |
| `_to_delete/data_runtime_stray_*/**` | Runtime database / temporary file / obsolete historical file | Disposable residue already staged by the earlier cleanup; remove after this inventory. |
| `_to_delete/verify_tmp_*/**` | Temporary file / generated archive | Disposable; remove after this inventory. |
| `logs/**`, `*.log`, `*.log.*` if present | Log | Disposable and ignored. None is required for submission. |
| Temporary browser profiles, traces, downloads, screenshots outside `docs/screenshots/**` | Temporary browser file | Disposable and ignored. No such file is required. |
| `.env`, `.env.*` except `.env.example` if present | Secret or environment file | Never package; ignored. No real environment file is required. |
| `.DS_Store`, editor metadata | Cache / OS metadata | Disposable and ignored. |

## Protected keep-list

The cleanup must not remove or modify the frozen model/calibrator, feature contract, model metadata, operational policy, blind evidence, release manifest/checksum, golden fixture, README evidence, screenshots, reproducibility scripts, tests, license, or exact locks.

## Authorized cleanup scope

Only the explicitly disposable cache, runtime-database, temporary, log, browser-residue, and OS-metadata families above may be removed. Source, artifacts, evaluation evidence, documentation, fixtures, configuration, and reports remain.
