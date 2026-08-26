# Final hardening baseline

Captured before the final-hardening dependency, benchmark, hygiene, or README changes on 2026-08-26 (Asia/Kolkata).

## Repository state

- Active branch: `submission-clean`
- HEAD: `d56927eabdd83c9d01eb66bf413ad56663073651`
- Rollback branch: `checkpoint/full-system-20260826` at the same commit
- Rollback tag: `pre-submission-cleanup-20260826` at the same commit
- Pre-existing worktree status: 18 modified paths, 408 deleted paths, and 77 untracked paths. This is the already-in-progress submission cleanup, not a clean Git baseline.
- No process was listening on TCP port 8000 before the checks.

## Protected and parity hashes

| Item | SHA-256 |
|---|---|
| Frozen model | `6c638fc05ca321e98c8b5417c477a58e2649bdd7e056bcd56e0d119d3eb80f88` |
| Calibrator (embedded in the same Joblib) | `6c638fc05ca321e98c8b5417c477a58e2649bdd7e056bcd56e0d119d3eb80f88` |
| Feature contract | `40ba9345c649a91cad9805b2d48b9607e9c179b042e70a682e71958e2d9bb634` |
| Model metadata | `98160e5f03c58fc9a5c442ecbf9b847dc56e70501543e9b1a279bb738bde98a2` |
| Frozen operational policy | `9afeba2df176c87287e86ff0402ef96b58e9386608d003b5702986be02b6ae95` |
| Blind metrics | `5fba17e8a8458c290934dece38ef70ef28d5b6eed93709ba9b8f3950a3130ef6` |
| Blind device summary | `b5c6a7ff1e925dfeff66d815b39bcc9716be06239e4d1276e931fd798c7f1a55` |
| Blind event decisions | `e6e6b2481c09edb44c1782165b97c5c59864890fd03ddbfdb991b1ec41605817` |
| Non-blind golden parity fixture | `a03f10528059d71bd148323b402bc37204186fff6f0df06146aeea755a7368bb` |
| Release manifest | `919a81a49c75b6b9ddf0697782357994752a9c5c0cdca1a9aaacb3594eea248b` |

## Verification baseline

- Release verification: passed; manifest version `card-testing-sentinel-release-1`; 44 features; `blind_rows_rescored: False`.
- Python: 111 tests passed in 4.64 seconds; 91.80% coverage; 80% gate passed.
- Frontend: 15 Node tests passed.
- Golden parity: passed independently against the non-blind fixture.
- Ruff: 87 files already formatted; lint passed.
- Readiness: `/health/live` and `/health/ready` both returned HTTP 200; readiness was `true` with no error.
- Python runtime: CPython 3.11.13.
- Baseline server was shut down after the health check.

This report intentionally records hashes without parsing or rescoring frozen blind rows.
