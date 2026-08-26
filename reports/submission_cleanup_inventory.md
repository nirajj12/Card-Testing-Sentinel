# Submission cleanup inventory

This inventory was captured on 2026-08-26 before any source, artifact, data,
test or documentation directory was moved or removed. The rollback tag
`pre-submission-cleanup-20260826` exists locally and on `origin`; both resolve
to `d56927eabdd83c9d01eb66bf413ad56663073651`.

## Baseline

- Working branch: `submission-clean`
- Git state before capture: clean
- Tracked files: 426
- Tracked bytes: 65,658,743
- All working-tree files excluding `.git`: 16,939
- Working-tree size including local environments/caches: 604 MiB
- Test baseline: 280 passed; 80% whole-repository coverage
- Runtime-focused baseline: 30 passed
- Ruff baseline: 174 files formatted; lint passed
- Live smoke: readiness, system and demo-scenario endpoints returned HTTP 200

The large difference between tracked and total files comes primarily from the
local `.venv`, caches, editable-install metadata and MLflow output. Every file
is covered by one of the path classifications below; generated/local groups are
classified as groups rather than listing thousands of dependency and cache
members individually.

## Classification

| Current path or complete path family | Classification | Cleanup disposition |
|---|---|---|
| `src/card_testing_sentinel/v2/phase4/app.py` and `api/` | runtime_required | Move into the clean app and API packages; remove generation labels from routes and responses. |
| `src/card_testing_sentinel/v2/phase4/service.py` | runtime_required | Move to `services/fraud_detection.py`; preserve causal transitions exactly. |
| `src/card_testing_sentinel/v2/phase4/state/` | runtime_required | Move to `persistence/`; preserve memory and SQLite behavior. |
| `src/card_testing_sentinel/v2/phase4/security.py` | runtime_required | Move to `security/identifiers.py`; preserve HMAC domain separation. |
| `src/card_testing_sentinel/v2/phase4/contracts.py` | runtime_required | Move to `api/contracts.py`; preserve strict validation. |
| `src/card_testing_sentinel/v2/phase4/demo.py` | runtime_required | Retain as the synthetic live demo service. |
| `src/card_testing_sentinel/v2/phase4/templates/` and `static/` | runtime_required | Move to `web/`; keep one same-origin frontend. |
| `src/card_testing_sentinel/v2/features/` | runtime_required, ml_development_required | Move into the clean feature package. |
| `src/card_testing_sentinel/v2/phase2b/engine.py` and `features.py` | runtime_required, ml_development_required | Consolidate with the feature engine/specification while preserving all 44 values and order. |
| `src/card_testing_sentinel/v2/phase2b/artifacts.py` | runtime_required | Move to `modeling/artifacts.py`; also used to load the immutable pickle. |
| Optimized scorer in `src/card_testing_sentinel/v2/phase2b/validation_policy.py` | runtime_required | Extract into `modeling/scorer.py`; discard historical validation orchestration. |
| `src/card_testing_sentinel/v2/phase2c/policy.py` | runtime_required, ml_development_required | Split into clean policy state, reasons and engine modules. |
| `src/card_testing_sentinel/v2/policy/rules.py` | runtime_required, ml_development_required | Retain as the single rules implementation. |
| `src/card_testing_sentinel/v2/data/contracts.py` | runtime_required, ml_development_required | Move to `domain/events.py`. |
| `src/card_testing_sentinel/v2/data/generator.py`, `validation.py` | ml_development_required | Retain clean synthetic generation and validation capabilities. |
| `src/card_testing_sentinel/v2/evaluation/{calibration,eda,metrics,sequential}.py` | ml_development_required | Retain clean training-only evaluation utilities. |
| `src/card_testing_sentinel/v2/modeling/{candidates,features,folds,training,weights}.py` | ml_development_required | Consolidate into the final training pipeline. |
| `src/card_testing_sentinel/v2/phase2b/{training,batch}.py` | ml_development_required | Extract final 44-feature training path; remove freeze/history coupling. |
| `src/card_testing_sentinel/v2/policy/{evaluation,selection}.py` and reusable replay logic | ml_development_required | Retain clean sequential evaluation and policy-selection functions only. |
| `artifacts/v2/phase2b/training/models/selected_model.joblib` | runtime_required | Move byte-for-byte to the final model artifact. Contains both selected logistic model and fitted isotonic calibrator. |
| `artifacts/v2/phase2b/training/models/{model_feature_contract.json,model_metadata.json}` | runtime_required, documentation_required | Move byte-for-byte to final model artifact directory. |
| `artifacts/v2/phase2c/confirmation/frozen_operational_policy.json` | runtime_required | Move byte-for-byte to the final policy artifact directory. |
| `artifacts/v2/phase3/blind/final_blind_metrics.json` | evaluation_evidence_required | Move byte-for-byte to final evaluation artifacts. Never rescore. |
| `artifacts/v2/phase3/blind/final_blind_device_summary.csv` | evaluation_evidence_required | Move byte-for-byte; dashboard filter source. |
| `artifacts/v2/phase3/blind/final_blind_event_decisions.csv` | evaluation_evidence_required | Move byte-for-byte; dashboard replay source. |
| Remaining `artifacts/v2/**` | historical_only, duplicate | Remove candidate tables, ledgers, amendments, freeze chains, diagnostics, intermediate predictions and duplicate artifacts. |
| `artifacts/models`, `artifacts/metrics`, `artifacts/predictions`, historical `artifacts/policy` | historical_only, obsolete | Remove the snapshot product and its evidence. |
| `data/frozen/**` | historical_only | Remove historical snapshot datasets. |
| `data/v2/development/**`, fresh/confirmation datasets | ml_development_required but too large | Remove generated data from submission; generation pipeline remains. |
| `data/v2/phase3/blind/**` | sensitive_or_local, historical_only | Remove raw blind dataset; retain only frozen result evidence. |
| `data/**/runtime/**`, `*.sqlite3`, `*.sqlite3-wal`, `*.sqlite3-shm` | generated_runtime | Remove and ignore; created only at runtime. |
| Root `src/card_testing_sentinel/{api,data,evaluation,features,modeling,policy,rules,static,templates}` | obsolete, historical_only | Remove the historical 26-feature snapshot application and its training/evaluation stack. |
| Remaining `src/card_testing_sentinel/v2/phase2b`, `phase2c`, `phase3`, `phase4` modules | historical_only, duplicate | Remove after runtime/development dependencies have clean homes and golden parity passes. |
| `scripts/run_app.py` | obsolete | Replace with the one clean application entry point. |
| `scripts/v2/phase4/{benchmark_live_api,run_app,verify_phase4}.py` | runtime_required/test_required | Rewrite as clean `scripts/{benchmark,run_app,verify_release}.py`. |
| Remaining root and generation/phase scripts | historical_only, duplicate | Replace with five clean pipeline entry points. |
| `tests/v2/phase4/**` | test_required | Move to clean unit/integration suites and update imports/routes. |
| `tests/v2/unit/**`, applicable model/evaluation tests | test_required, ml_development_required | Retain focused feature, contract, grouped-fold and metric coverage. |
| Historical root tests and phase freeze/access/amendment tests | historical_only, obsolete | Remove; they verify deleted products or historical execution chains. |
| `tests/fixtures/golden/live_parity.json` | test_required | Retain as non-blind behavioral parity baseline. |
| `README.md` | documentation_required | Replace with judge-facing product documentation. |
| `docs/v2/{data_contract,evaluation_protocol,live_serving_contract,known_gaps}.md` | documentation_required | Consolidate into clean architecture, dataset, evaluation, API and limitation docs. |
| Phase closeouts, audits, diagnoses and historical reports | historical_only | Remove after this inventory; Git tag preserves them. |
| Final figures that directly explain retained blind evidence | evaluation_evidence_required | Retain only if referenced by final documentation; otherwise remove duplicate figures. |
| `configs/v2/features.yaml` | runtime_required, ml_development_required | Move to `configs/features.yaml`. |
| Current runtime config and final training/policy settings | runtime_required, ml_development_required | Consolidate into `configs/{app,training,policy}.yaml`. |
| Remaining configs and historical locks | historical_only, duplicate | Remove after exact final lock/configs are created. |
| `pyproject.toml`, `environment.yml`, `.gitignore`, CI | documentation_required, test_required | Rewrite for the single clean product. |
| `.env.example` | documentation_required | Retain without a real secret. |
| `.venv/**` | sensitive_or_local | Remove from submission and keep ignored. |
| `.pytest_cache/**`, `.ruff_cache/**`, `**/__pycache__/**`, `*.pyc`, `.coverage*` | generated_runtime | Remove and ignore. |
| `src/card_testing_sentinel.egg-info/**` | generated_runtime | Remove and ignore. |
| `mlruns/**`, `logs/**` | generated_runtime | Remove and ignore. |
| `razorpay (1).zip` | historical_only | Remove downloaded archive. |

## Final dependency targets

The retained runtime dependency chain will be:

`app` → API routers → fraud-detection service → feature engine + frozen scorer
+ policy engine → persistence and identifier protection. The artifact registry
will depend only on the clean release manifest and retained runtime/evaluation
artifacts. The web layer will depend only on clean `/api/...` routes.

The retained ML-development dependency chain will be:

synthetic generator → lifecycle validation → causal batch feature engine →
device-grouped training → calibration → sequential policy evaluation. It will
not import or read the saved blind evaluation artifacts.
