# Final hardening report

> **Historical hardening checkpoint.** The test counts, runtime description and
> latency measurements below record the 2026-08-26 system and are not current
> submission headlines. See `reports/README.md` for the active evidence map and
> `phase_4c_razorpay_e2e_latency.md` for current latency.

## Status

**completed_with_accepted_risks** — the requested hardening and submission packaging are complete. There are no remaining published dependency advisories in either the final development environment or clean runtime environment. Accepted risks are the explicitly disclosed product constraints that this pass was not authorized to redesign: synthetic data, single-process SQLite, a global transition lock, no production authentication or tenant isolation, no distributed state, and no model-drift monitoring. The tests also emit one development-only Starlette warning recommending a future migration from the deprecated HTTPX-backed `TestClient` adapter to `httpx2`; it does not affect the Uvicorn runtime or audit result.

## Verification summary

- Python: **112 passed**, **91.58%** line coverage.
- Frontend modules: **15 passed**.
- Ruff formatting/lint: pass.
- npm audit: **0** vulnerabilities.
- pip-audit: **51 advisory records across 10 packages before; 0 after** in both final environments.
- Golden parity, release manifest, protected hashes and 44-feature contract: pass.
- Clean non-editable wheel install: pass on CPython 3.11.13.
- Installed Chromium: all seven scenarios and all four required viewports pass; developer log empty.
- SQLite: WAL, `quick_check=ok`, idempotency/conflict/late-event/block/reset/restart contracts pass.
- No server, runtime database, SQLite sidecar, log or cache remains in the repository.
- No external deployment, upload, cloud resource, DNS change, commit, push, merge or tag was performed.

## Files changed by final hardening

- Dependency and build controls: `pyproject.toml`, `requirements-runtime.lock`, `requirements-dev.lock`, `requirements-lock.txt`, `environment.yml`, `Dockerfile`, `.github/workflows/ci.yml`.
- Runtime/reproducibility: `src/card_testing_sentinel/common/paths.py`, `src/card_testing_sentinel/app.py`, `src/card_testing_sentinel/features/specification.py`, `src/card_testing_sentinel/modeling/registry.py`, `scripts/benchmark.py`.
- Verification: `tests/conftest.py`, `tests/integration/test_frontend_contract.py`, `tests/integration/test_demo_orchestration.py`, `tests/integration/test_replay_dashboard.py`, `tests/integration/test_final_hardening_state_contract.py`.
- Hygiene/submission: `.gitignore`, `README.md`, `docs/deployment.md`, and the final-hardening reports under `reports/`.

The repository already contained a large classified submission-cleanup working tree before this pass. That preexisting scope is preserved in `reports/final_hardening_baseline.md` and `reports/final_hardening_inventory.md` rather than being misattributed here.

## Dependency outcome

The complete advisory-by-advisory classification is in `reports/dependency_security_audit.md`. Web-facing FastAPI, Starlette, Jinja2, Uvicorn, h11, Click and IDNA were upgraded and retested. Development/build-only FontTools, Pillow, pytest, pip and setuptools were upgraded or separated from runtime. scikit-learn 1.6.1, NumPy 1.26.4, SciPy 1.14.1 and Joblib 1.4.2 remain unchanged. The artifact loads without `InconsistentVersionWarning`, and incompatibility still fails closed.

## Performance

- Model + calibration + policy: p50 **0.037208 ms**, p95 **0.041041 ms**, p99 **0.062500 ms**, maximum **41.992916 ms**, mean **0.040913 ms**, throughput **24,442.29/s**, failures **0**.
- End-to-end normal: p50 **2.642980 ms**, p95 **4.404375 ms**, p99 **4.838084 ms**, failures **0**.
- End-to-end burst: p50 **2.957060 ms**, p95 **4.851667 ms**, p99 **5.442625 ms**, failures **0**.
- End-to-end mixed: p50 **2.965500 ms**, p95 **4.904584 ms**, p99 **5.043458 ms**, failures **0**.
- Cold start + first decision: **342.914 ms**.
- Idempotent retry: p50 **1.527021 ms**, p95 **2.519083 ms**, p99 **2.701709 ms**, failures **0**, fresh scores **0**.

Detailed counts, maxima, means, throughput and instrumentation are in `reports/decision_path_benchmark.md`.

## Protected-state confirmation

All nine recorded protected hashes match the baseline, including model/calibrator, feature contract, metadata, policy, blind metrics, blind device summary, blind decisions, golden fixture and release manifest. Feature count remains 44 and feature order is unchanged. No blind data was rescored. Live startup, benchmark, clean install, browser and final state tests recorded `blind_row_load_count=0` and artifact-load count 1 per process.

The initial baseline suite exposed that legacy replay tests opened frozen saved-projection CSVs. The final harness now fails if either protected row CSV is semantically opened; replay API tests use explicit saved-replay fixtures. The final 112-test verification completed with this guard active.

## Deployment handoff

Production target: CPython 3.11 (Docker pins 3.11.15), `python scripts/run_app.py`, required `CTS_HMAC_SECRET`, readiness route `/health/ready`, one instance, and a persistent mount at `/app/data/runtime`. Provider/storage tradeoffs and the pre-deployment gate are in `docs/deployment.md`. External deployment still requires explicit approval.
