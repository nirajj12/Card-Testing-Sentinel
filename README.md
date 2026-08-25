# Card-Testing Sentinel

Card-Testing Sentinel is a defensive machine-learning project for identifying
payment card-testing attacks while controlling false positives on legitimate
customers and flash-sale traffic. Phase 5 serves the frozen Phase 3 model and
Phase 4 rules-only policy through a local FastAPI application and same-origin,
read-only replay dashboard. It does not retrain, retune, or rerun final evaluation.

V1 is now an immutable historical release. Its evaluated split is the **legacy
seen V1 benchmark** and cannot support V2 selection or generalization claims.
V2 Phase 1 is a separate pre-authorization data and causal-feature foundation;
it contains development train/validation data only and no trained V2 model,
calibration, policy, blind-test seed, blind-test rows, or V2 inference API.

## V2 Phase 1 commands

Generate the deterministic development lifecycle bundle, rebuild causal
features through the shared incremental engine, and validate it:

```bash
python scripts/v2/generate_development_data.py
python scripts/v2/build_development_features.py
python scripts/v2/validate_development_data.py
```

Run a second clean generation into a separate directory by calling
`write_development_bundle(config_path, output_dir)` and compare the three hashes
recorded in `data/v2/development/manifest.json`. The checked release produces
10,000 devices, 12,686 sessions, 26,760 scored authorization requests, and
61,862 lifecycle events. Device splits are 8,000 train and 2,000 validation.

V2 decisions are pre-authorization: a request emits one causal feature row,
the later processor outcome commits history without scoring, and a later
checkout completion updates history without scoring. See `docs/v2/` for the
data, evaluation, live-serving, limitation, and blind-challenge contracts.

## Dataset safeguards

The synthetic v4 dataset is frozen. It must not be regenerated, normalized, or
have its distributions tuned after evaluation. These authoritative files are
locked by SHA-256:

- `raw_events.csv`: `1d9bc5a1da647cbe33637d904516e5045e7a4bc3f5c88841490e8bd2e5d17e34`
- `events_with_features.csv`: `c9d5f3ea2a62a97ce9e2aa6e7e7f14a8e53828514701adebcee10ea7fb264aaa`
- `device_splits.csv`: `b6562785964dbcf1eaa8340791fa07711e07c69c231ab14360fb00962704678b`

The verified provenance archive has SHA-256
`9171004f903729b150564b8c53d3127523b22530e6f292e97ebe836433bf85f6`.
Its three internal CSVs are byte-identical to the files in `data/frozen/`.

An authorization will be scored immediately after its outcome is observed. Its
features may include that authorization and its observed outcome, but never a
later event. A decision therefore affects the next authorization. Model rows
are authorization events only. Checkout-completion events affect causal state
but are excluded from model training and authorization scoring.

Future training must select the ordered 26-column allowlist from
`features/spec.py` directly. It must never infer features by subtracting a
blacklist. Population, subtype, scenario, label, identifiers, raw amount, and
raw outcome fields are excluded. `scenario_tag` is evaluation-only session
metadata: it is stable within a session but can change between sessions for a
returning device.

The frozen train, validation, and test assignments are device-level. No device
may cross partitions, and the test partition is reserved for integrity checks
until the model, threshold, and policy are frozen.

## Setup and checks

Create or update the Conda environment from the repository root:

```bash
conda env update --file environment.yml
conda activate card-testing-sentinel
python -m pip install -e '.[dev]'
```

Run the same checks used by CI:

```bash
ruff format --check .
ruff check .
pytest --cov-report=term-missing
```

Validate the complete frozen data contract:

```bash
python scripts/validate_dataset.py --config configs/base.yaml
```

The deterministic result is written to
`reports/data_validation_report.json`. An overall status of `pass` means every
required integrity, schema, relationship, split, feature-domain, and sampled
causality check passed. Row, session, device, and overlapping scenario-device
counts are reported with explicit units.

Run the Phase 3 pipeline in order:

```bash
python scripts/analyze_training_data.py \
  --config configs/base.yaml \
  --training-config configs/training.yaml
python scripts/train_baselines.py \
  --config configs/base.yaml \
  --training-config configs/training.yaml
```

The training command refuses to fit if the Phase 2 report is failed or stale,
if frozen checksums change, or if the checksum-current EDA summary is not
passed. Inspect local experiment runs with:

```bash
MLFLOW_ALLOW_FILE_STORE=true mlflow ui --backend-store-uri ./mlruns
```

## Phase 3 findings

EDA used 7,372 training authorization rows from 2,975 training devices. It
constructed no validation or test model view and recorded zero held-out rows.
The training set contains 2,660 legitimate devices producing 4,347 rows and
315 attacker devices producing 3,025 rows. A device produced a median of one
authorization and a maximum of 20, so unweighted rows would substantially
overrepresent high-volume attackers.

No feature is near-constant. The strongest one-feature threshold was
`cards_this_session >= 2`, with device-weighted training F1 0.6924 and average
precision 0.6884; it did not trigger the 0.90 shortcut guardrail. Thirty pairs
have absolute Pearson or Spearman correlation of at least 0.95. These include
the exact complements `decline_ratio_so_far`/`approval_ratio_so_far` and
`repeated_amount_ratio`/`unique_amount_ratio`, the identical IP session/device
counts, and several velocity/card-count features. All 26 frozen features remain
in the baseline. Because of this redundancy, individual Logistic Regression
coefficients are not independently reliable even with L2 regularization.

Training-only subgroup medians confirm intentional hard-negative overlap.
`flash_hard_retry` and `normal_bad_luck` both have median cumulative decline
ratio 1.0, compared with 0.667 for evasive and 0.5 for patient attacks.
Flash processor-strain traffic has median five-minute IP device count 9, while
burst attacks have median 1. These are row-distribution measurements, not
device prevalence or final performance claims.

Every validation device has aggregate evaluation weight 1. Training combines
inverse rows-per-device with inverse device-class frequency; the aggregate
class weights are equal. Three-fold `StratifiedGroupKFold` uses device groups,
with holdout device counts 991, 992, and 992 and zero overlap in every fold.
Training-CV selected `C=10` for Logistic Regression (mean PR-AUC 0.8926) and
the regularized HistGradientBoosting configuration (mean PR-AUC 0.9140).

At the primary validation-only 3% legitimate false-positive budget:

| Method | Actual FPR | Precision | Attacker row recall | PR-AUC |
|---|---:|---:|---:|---:|
| Fixed rules | 1.30% | 83.41% | 55.44% | n/a |
| Logistic Regression | 2.67% | 79.31% | 87.00% | 0.9112 |
| HistGradientBoosting | 2.60% | 80.14% | 89.37% | 0.9346 |

HistGradientBoosting is the Phase 3 validation-stage champion. Its row-level
recall is 96.15% for burst, 80.62% for evasive, and 81.78% for patient attacks.
Its false-positive rates are 1.41% on normal, 7.06% on flash-sale,
38.51% on `flash_hard_retry`, and 7.49% on `normal_bad_luck`. The high
hard-retry rate is an important warning: a good aggregate false-positive rate
does not mean the difficult legitimate subgroups are solved. Rules are more
precise but do not match ML recall at the same budget.

These are validation-stage, device-weighted authorization-row metrics. They do
not measure unique-device detection, time to detection, intervention outcomes,
or final test performance.

## Phase 3 artifacts

- EDA summary and tables: `artifacts/metrics/training_eda_summary.json`,
  `training_feature_summary.csv`, `training_feature_correlations.csv`, and
  `training_univariate_strength.csv`.
- CV and validation results: `artifacts/metrics/cross_validation_results.csv`,
  `validation_metrics.json`, and `validation_operating_points.csv`.
- Models: `artifacts/models/logistic_regression.joblib`,
  `hist_gradient_boosting.joblib`, and `champion_metadata.json`.
- Validation-only predictions: `artifacts/predictions/validation_predictions.csv`.
- Four EDA and three validation figures: `reports/figures/`.
- Local experiment tracking: `mlruns/`, experiment
  `card-testing-sentinel-baselines`.

## Project layout

- `configs/` contains non-secret application defaults.
- `src/card_testing_sentinel/common/` contains configuration, logging, and the
  small exception layer.
- `data/frozen/` contains the manifest and approved immutable dataset artifacts;
  `data/runtime/` is for temporary application state.
- `artifacts/`, `reports/`, `logs/`, and `mlruns/` hold generated local output.
- `tests/unit/` contains focused foundation tests.

Future code must not log full card tokens, payment credentials, secrets, raw
user data, or complete event rows. Identifiers and dataset counts must be logged
only when deliberate and privacy-safe.

The local API and dashboard are documented below. No database, deployment, or
monitoring service is implemented. Phase 4 documents the frozen sequential
policy and its guarded one-time final evaluation.

## Phase 4 sequential policy and final evaluation

Phase 4 uses post-authorization timing: authorization `k` is processed, its
outcome and causal features are scored, and the selected action applies to
authorization `k + 1`. Consequently, `block_next_attempt` never prevents the
authorization that triggered it. Rows recorded after the first block are
marked only as replay-estimated potentially preventable attempts.

Three fixed policy forms were selected using validation devices only:

- Rules-only reviews and blocks at frozen integer rule-score boundaries.
- ML-only uses separate frozen HGB review and block score boundaries.
- Combined uses the frozen ML block boundary, a fixed ML/rule joint block,
  then ML-or-rule review logic.

The buildathon validation assumptions allow at most 5% of legitimate devices
to receive review-or-higher, 1% to be blocked, 3% of flash-sale devices to be
blocked, 15% of devices ever tagged `flash_hard_retry` to be blocked, and 10%
of devices ever tagged `normal_bad_luck` to be blocked. These are synthetic
evaluation assumptions, not production Razorpay limits.

Validation selected rules-only with review and block rule score 3. It blocked
47/67 attacker devices (70.15%) and 4/570 legitimate devices (0.70%). The
flash-sale result was 3/120 and the hard-retry result was 3/22, both within the
integer validation allowances. ML-only and combined each blocked 29/67
attacker devices using frozen ML threshold `0.999410363031`.

Detection coverage always divides by every attacker device, including devices
never detected. Detection position is one-indexed. Attempts processed through
detection include the triggering authorization; cards before detection exclude
its card, while cards processed through detection include it. Duration starts
at the device's first authorization. Row recall and unique-device detection
coverage are separate metrics.

The guarded final test ran once on 1,652 authorizations from 638 devices. The
static frozen HGB threshold produced PR-AUC 0.9267, ROC-AUC 0.9825, precision
87.18%, row recall 85.18%, F1 0.8617, and row FPR 1.49%.

The frozen rules policy blocked 47/68 attacker devices (69.12%): 37/37 burst,
10/21 evasive, and 0/10 patient devices. It detected 0/68 by attempt 1, 12/68
by attempt 3, 42/68 by attempt 5, and 47/68 by attempt 10. Twenty-one attackers
(30.88%) were never detected. Among detected attackers, median attempts
processed through detection was 4, median distinct cards before detection was
2, median distinct cards through detection was 3, and median time to detection
was 11.58 seconds.

The rules policy blocked/reviewed 4/570 legitimate devices (0.70%): 0/450
normal, 4/120 flash-sale, 0/54 bad-luck, and 3/22 hard-retry devices. The test
flash-sale block rate was therefore 3.33%, exceeding the frozen 3% guardrail by
one device. This is preserved as an honest held-out warning; the policy was not
changed after test access. ML-only and combined each blocked 29/68 attackers
(42.65%) and 0/570 legitimate devices.

The replay estimates 377 later recorded authorizations after rules-policy
detection. This is an offline upper-bound under the assumption that blocking
the next attempt ends the sequence, not observed fraud prevention or a causal
business result.

Authoritative Phase 4 artifacts are under `artifacts/policy/`,
`artifacts/metrics/`, and `artifacts/predictions/`. Validation and final-test
figures are under `reports/figures/`. The frozen policy SHA-256 is
`d7a3d631e4c095d1bb36614c21714fc3aa6d19b7a56f04f841c0b6f9836cc604`.
The final-test command is non-overwriting and now refuses a second execution.

All results are synthetic buildathon evidence, not production Razorpay
performance or production-ready intervention thresholds. Database, deployment,
and monitoring remain unimplemented.

## Phase 5 application

The local application loads and verifies the frozen model, policy, final
metrics, and replay artifacts once at startup. It never trains, selects a
threshold, or reruns final evaluation.

```text
feature snapshot -> advisory HGB + frozen rules -> frozen policy action
frozen final artifacts -> read-only API -> same-origin replay dashboard
```

Install and launch:

```bash
conda activate card-testing-sentinel
python -m pip install -e '.[dev]'
python scripts/run_app.py
```

Open `http://127.0.0.1:8000`. JSON endpoints are `/health/live`,
`/health/ready`, `/api/v1/system`, `/api/v1/evaluate`, `/api/v1/metrics`,
`/api/v1/devices`, and `/api/v1/devices/{device_id}/timeline`.

`POST /api/v1/evaluate` accepts optional synthetic correlation IDs and a
`features` mapping containing exactly the 26 finite numeric frozen features.
It does not accept card data, IPs, labels, population, subtype, or scenarios.
Raw-transaction online feature state is outside this milestone. The HGB result
is advisory; rules-only remains the immutable intervention champion and
`block_next_attempt` affects only a later authorization.

The offline dashboard shows immutable metrics, the flash-sale target miss,
10/10 missed patient attackers, frozen-method comparison, and safe synthetic
device replays. It maps tokens to `Card 1`, `Card 2`, and so on without exposing
the underlying values. There are no CDN, threshold, retraining, test-rerun,
attack-generation, or raw-export controls.

If readiness returns 503, verify the protected hashes in `configs/app.yaml`
against the authoritative artifacts. Never regenerate an artifact to make
readiness pass. This remains a synthetic, defense-only student prototype—not a
production system or evidence of real Razorpay performance.
