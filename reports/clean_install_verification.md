# Clean-install verification

Final result: **passed** on 2026-08-26 using a new CPython 3.11.13 virtual environment and an isolated copy containing repository files only.

## Installation path

1. Created a new Python 3.11 virtual environment outside the repository.
2. Installed pip 26.2.1 and setuptools 84.0.0.
3. Installed `requirements-runtime.lock` with `--no-deps`.
4. Built and installed the project as a non-editable wheel with `--no-deps --no-build-isolation` from the isolated repository copy.
5. Started the installed application from that copy with a temporary HMAC secret and file-backed SQLite database.

The clean pass caught and repaired two packaging issues before final verification: Pandas was initially misclassified as development-only despite supporting the retained immutable replay API, and installed-wheel project-root discovery initially assumed an editable source layout. The final runtime lock and root resolver correct both issues.

## Canonical runtime versions

| Package | Version |
|---|---:|
| Python | 3.11.13 |
| pip | 26.2.1 |
| setuptools | 84.0.0 |
| FastAPI | 0.141.1 |
| Starlette | 1.6.0 |
| Uvicorn | 0.52.4 |
| h11 | 0.16.0 |
| Jinja2 | 3.1.6 |
| Pydantic / core | 2.13.4 / 2.46.4 |
| Pandas | 3.0.5 |
| scikit-learn | **1.6.1 unchanged** |
| NumPy | **1.26.4 unchanged** |
| SciPy | **1.14.1 unchanged** |
| Joblib | **1.4.2 unchanged** |

The remaining exact runtime transitive versions are recorded in `requirements-runtime.lock`.

## Smoke and restart evidence

- Readiness returned HTTP 200 and `ready: true`.
- Normal-customer decisions: `allow`, `allow`.
- Burst decisions: `allow`, `allow`, `allow`, then five real `block` decisions.
- The first burst block occurred at attempt 4; four later attempts remained independently scored.
- SQLite contained 10 requests and 6 lifecycle events.
- SQLite reported `journal_mode: wal` and `quick_check: ok`.
- The server was stopped and restarted against the same database; all 10 requests and 6 events were recovered.
- Artifact load count was 1 on each process.
- Blind-row load count was 0 throughout installation, smoke and restart verification.
- The final server was stopped and the temporary runtime database was removed.
