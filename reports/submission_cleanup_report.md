# Submission cleanup report

Date: 2026-08-26  
Branch: `submission-clean`  
Final status: **blocked_verification**

The repository is now one clean Card-Testing Sentinel product with one runtime,
one API namespace, one dashboard, one frozen model/calibrator artifact, one
frozen policy and one immutable blind-evaluation evidence set. Behavioral,
integrity, security, clean-install and real-browser checks passed. The only
unresolved verification is an actual Docker build/run because this workstation
has no Docker-compatible executable installed.

## Safety and rollback

- The working tree was clean before cleanup began.
- The local and remote rollback tag `pre-submission-cleanup-20260826` both
  resolve to `d56927eabdd83c9d01eb66bf413ad56663073651`.
- No commit, push, reset, checkout, rebase, merge or tag mutation was performed
  during cleanup.
- The pre-clean inventory is retained in
  `reports/submission_cleanup_inventory.md`.

## Before and after

| Measure | Before | Final | Reduction |
|---|---:|---:|---:|
| Tracked/deliverable files | 426 | 115 | 73.0% |
| Deliverable bytes | 65,658,743 | 1,993,223 | 97.0% |
| All workspace files, including the local environment and caches | 16,939 | 115 | 99.3% |
| Workspace disk use, including Git metadata | 604 MiB | 15.1 MiB | — |

The final counts exclude `.git`. The original working-tree total included a
local virtual environment, caches, MLflow output and generated artifacts; the
tracked/deliverable comparison is the conservative repository reduction.

## Retained product

- FastAPI pre-authorization service with strict raw-event contracts.
- HMAC-SHA256 domain separation for device, session, card and IP references.
- One causal 44-feature engine used by live and development workflows.
- Frozen logistic model and fitted isotonic calibrator loaded once at startup.
- Stateful allow/review/block policy with reason codes, decay and post-block
  scoring.
- SQLite/WAL persistence, idempotency, conflict handling and restart recovery.
- Read-only blind-evidence API and replay explorer; blind rows are never
  rescored.
- Responsive Overview, Live Detection, Blind Replay and System dashboard.
- Synthetic generation, validation, EDA, grouped training, calibration and
  sequential evaluation pipelines.

## Removed or consolidated

- Historical snapshot applications and all phase/version source-package trees.
- Duplicate models, policies, metrics, predictions and feature contracts.
- Freeze chains, access ledgers, amendments, candidate grids, diagnoses,
  closeouts and internal execution-history reports.
- Raw development, validation and blind datasets. Only immutable blind result
  evidence remains.
- Obsolete scripts, tests, configuration families, figures and downloaded
  archives.
- MLflow output, local environment files, SQLite runtime state, caches,
  coverage files, bytecode and editable-install metadata.

The old serialized Python class path remains encoded inside the byte-identical
model pickle. A narrow startup compatibility registration maps that class to
the clean artifact class; no historical package tree is shipped. Historical
identifiers inside immutable artifact bytes and the parity fixture were also
left unchanged by design.

## Immutable release evidence

| Artifact | SHA-256 |
|---|---|
| Model plus fitted isotonic calibrator | `6c638fc05ca321e98c8b5417c477a58e2649bdd7e056bcd56e0d119d3eb80f88` |
| Feature contract | `40ba9345c649a91cad9805b2d48b9607e9c179b042e70a682e71958e2d9bb634` |
| Model metadata | `98160e5f03c58fc9a5c442ecbf9b847dc56e70501543e9b1a279bb738bde98a2` |
| Operational policy | `9afeba2df176c87287e86ff0402ef96b58e9386608d003b5702986be02b6ae95` |
| Blind metrics | `5fba17e8a8458c290934dece38ef70ef28d5b6eed93709ba9b8f3950a3130ef6` |
| Blind device summary | `b5c6a7ff1e925dfeff66d815b39bcc9716be06239e4d1276e931fd798c7f1a55` |
| Blind event decisions | `e6e6b2481c09edb44c1782165b97c5c59864890fd03ddbfdb991b1ec41605817` |
| Release manifest | `919a81a49c75b6b9ddf0697782357994752a9c5c0cdca1a9aaacb3594eea248b` |

The selected model object contains both the fitted base estimator and fitted
calibrator. The manifest therefore records logical model and calibrator entries
that intentionally reference the same protected file and hash. Release
verification returned `blind_rows_rescored: False` and a 44-feature contract.

## Golden parity

Before restructuring, a deterministic non-blind burst was captured at
`tests/fixtures/golden/live_parity.json` with SHA-256
`a03f10528059d71bd148323b402bc37204186fff6f0df06146aeea755a7368bb`.
The test compares all 44 ordered feature values, raw score, calibrated risk
score, rule score, action, reasons and state version to tolerance `1e-12`.

It also verifies exact retry idempotency, conflicting retry rejection, late
event rejection and continued post-block scoring. The preserved decision path
is allow for attempts 1–3 and block for attempts 4–10, with state versions
`1, 3, 5, 7, 8, 9, 10, 11, 12, 13`.

## Verification results

### Passed

- Fresh Python 3.11.13 environment created from `requirements-lock.txt`: 44
  packages plus the editable project installed successfully.
- Tests: **32 passed**.
- Whole-repository coverage: **91%** (`1,974` statements, `182` missed), above
  the CI gate of 80%.
- Ruff: 77 files formatted; all lint checks passed.
- Release manifest, artifact hashes and 44-feature contract verified.
- Golden parity passed at `1e-12`; the blind evidence was not rescored.
- API contract checks passed for credential/client-feature rejection,
  idempotency, HTTP 409 conflicts, late events and post-block scoring.
- Live SQLite smoke passed with WAL and `quick_check=ok`; an exact request was
  idempotent, a changed retry returned 409, and state/timeline survived restart.
- Persistence scan found no raw card token, IP, device ID or HMAC secret.
- Public routes use `/api/...`; no versioned API namespace remains.
- Public documentation and route/source layout contain no historical phase API
  structure. Immutable evidence and the inventory are intentional exceptions.

### Real-browser QA

The running application was tested through the in-app browser at 1440×1000,
768×900 and 390×844.

- Exact title: `Card-Testing Sentinel · Fraud Operations`.
- All four views rendered with no horizontal overflow.
- No browser console warnings or errors remained.
- Overview displayed the frozen action distribution, subtype coverage,
  limitations and successful 5,254-request feature-parity evidence.
- The live burst scenario produced allow at attempts 1–3 and block from attempt
  4 while continuing to score later attempts.
- Blind filters returned saved burst devices and a 12-attempt immutable
  allow/review/block timeline without invoking model scoring.
- System view reported readiness, 44 server-side features, verified manifest,
  WAL persistence and a single startup artifact load.

Browser QA initially exposed an Overview payload mismatch left by the cleanup.
The frontend/API contract was corrected, the meaningless empty latency card was
replaced with recorded feature-parity evidence, and the complete browser suite
then passed.

### Blocked verification

`docker`, `podman` and `colima` are not installed or available on this Mac.
Consequently, the Dockerfile and CI definition received static review, but the
required image build, container readiness smoke and named-volume restart test
could not be executed. The final status is therefore `blocked_verification`,
not `completed`.

## Final clean tree

```text
.
├── .github/workflows/ci.yml
├── .dockerignore
├── .env.example
├── .gitignore
├── Dockerfile
├── LICENSE
├── README.md
├── artifacts
│   ├── evaluation
│   │   ├── blind_device_summary.csv
│   │   ├── blind_event_decisions.csv
│   │   └── blind_metrics.json
│   ├── model
│   │   ├── feature_contract.json
│   │   ├── metadata.json
│   │   └── risk_model.joblib
│   ├── policy/operational_policy.json
│   ├── release_manifest.json
│   └── release_manifest.sha256
├── configs
│   ├── app.yaml
│   ├── features.yaml
│   ├── policy.yaml
│   └── training.yaml
├── docs
│   ├── api.md
│   ├── architecture.md
│   ├── dataset.md
│   ├── limitations.md
│   └── model_evaluation.md
├── environment.yml
├── pipelines
│   ├── analyze_training_data.py
│   ├── build_features.py
│   ├── evaluate_model.py
│   ├── generate_synthetic_data.py
│   ├── train_model.py
│   └── validate_dataset.py
├── pyproject.toml
├── reports
│   ├── submission_cleanup_inventory.md
│   └── submission_cleanup_report.md
├── requirements-lock.txt
├── scripts
│   ├── benchmark.py
│   ├── run_app.py
│   └── verify_release.py
├── src/card_testing_sentinel
│   ├── api
│   ├── common
│   ├── domain
│   ├── features
│   ├── ml
│   ├── modeling
│   ├── persistence
│   ├── policy
│   ├── security
│   ├── services
│   ├── web
│   │   ├── static
│   │   └── templates
│   └── app.py
└── tests
    ├── fixtures/golden/live_parity.json
    ├── integration
    └── unit
```

## Known boundaries

- Evaluation is synthetic and cannot establish real-world Razorpay fraud
  performance.
- No blind attacker was detected within the first three attempts; patient and
  evasive attacks remain harder, and 29/300 attackers were never detected.
- The risk score is not a guaranteed fraud probability.
- SQLite plus a global transition lock is a single-process prototype.
- Production use needs real merchant validation, auth, rate limits, distributed
  state/idempotency, secret management, audit controls, monitoring, drift
  detection and review feedback.
