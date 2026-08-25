# PHASE 2 CLOSED — BLOCKED / NO FEASIBLE POLICY

## Passed correctness checks

- V1 read-only dataset validation: 86/86 checks passed.
- V2 read-only development validation: 27/27 checks passed.
- All 23 V1 release-manifest entries match.
- Every V2 Phase 1 dataset, manifest, configuration, feature-specification, state,
  and engine hash matches the Phase 1 baseline.
- The authoritative training freeze is
  `b3eee5234af43bb87cb8fe957089961f25b0b90da22227ced41431e36d0aae13`.
  Its 23 frozen training artifacts and sources verify.
- Five device folds contain 1,600 training devices each, with zero overlap and
  no validation device.
- Model reload parity and the two clean training executions passed at freeze
  time. The selected training-only base model was HGB with learning rate 0.08,
  15 leaves, 160 iterations and L2 regularization 2.0. Isotonic calibration was
  selected with independently evaluated device groups.
- The complete test suite passed 75/75 in the available Python 3.13 runtime,
  including six hand-constructed Phase 2 lifecycle/weight/fold/grid tests.
- No V2 blind challenge, final-test artifact, API, or dashboard exists. No V2
  champion policy or `frozen_policy.json` exists.

## Validation infeasibility

The frozen configuration enumerates **32**, not 36, valid candidates: 8
rules-only, 20 ML-only, and 4 combined. The strict combined constraint accepts
only `review_score=2` with `block_support_score=3`. The 32-row table matches the
frozen enumeration exactly, has unique candidate IDs, and contains zero
feasible candidates. No partial table was accepted.

Closest rules-only candidate `policy_007` uses review score 4 and block score
6. It passed every block allowance and all review allowances except
normal_bad_luck:

| Legitimate group | Review-or-higher / denominator (allowance, excess) | Block / denominator (allowance, excess) | Result |
|---|---:|---:|---|
| normal_standard | 0/1200 (24, 0) | 0/1200 (6, 0) | pass |
| normal_bad_luck | 6/100 (5, **1**) | 0/100 (2, 0) | **fail** |
| flash_standard | 0/300 (15, 0) | 0/300 (9, 0) | pass |
| flash_hard_retry | 1/100 (10, 0) | 0/100 (5, 0) | pass |
| overall legitimate | 7/1700 (51, 0) | 0/1700 (17, 0) | pass |

Its review-or-higher attacker counts are burst 114/120, evasive 4/90, patient
25/90; never detected counts are therefore burst 6, evasive 86, patient 65.
Worst-subtype coverage is 4/90 = 4.44%. Block counts are burst 71/120,
evasive 2/90, patient 2/90.

Closest ML candidate `policy_023` uses review threshold 0.45 and block threshold
0.90. It reviews 120/120 burst, 90/90 evasive and 90/90 patient devices, with
zero never detected. Legitimate counts are normal_standard 6 review / 1 block,
normal_bad_luck 31 / 8, flash_standard 1 / 0, and flash_hard_retry 11 / 0.
It fails flash_hard_retry review by 1, normal_bad_luck review by 26, and
normal_bad_luck block by 6. Overall it is 49/1700 review-or-higher and 9/1700
blocked, both within overall allowances.

Closest combined candidate `policy_031` uses ML review/block thresholds
0.40/0.85, rule review score 2, and block-support score 3. It reviews every
attacker device, with zero never detected. Legitimate counts are
normal_standard 7 review / 0 block, normal_bad_luck 68 / 0, flash_standard
1 / 0, and flash_hard_retry 33 / 0. It fails normal_bad_luck review by 63,
flash_hard_retry review by 23, and overall review by 58. Its worst-subtype block
coverage is evasive 37/90 = 41.11%.

## Controlled post-access execution amendment

The original training-freeze hash was
`103e835f0a17e7ea7c5757e7c2abd49ecfa4b3586f6b853412e96789e88e791c`.
The authoritative re-executed freeze immediately before validation was
`b3eee5234af43bb87cb8fe957089961f25b0b90da22227ced41431e36d0aae13`,
created at 2026-08-25T13:59:19.992315Z. First validation access was
2026-08-25T13:59:34.470123Z.

`evaluation.py` was not included in the authoritative freeze's 23-entry source
hash list, which is a freeze-completeness limitation. After validation access:

1. Its feature-parity tolerance changed from `1e-12` to the already frozen
   Phase 1 six-decimal CSV tolerance `5e-7`.
2. It added a cache that passes the immediately preceding raw probability to
   the calibrator instead of scoring the same row twice.

The source hashes progressed from
`6fae0dbf...15f58` to `87743311...0163`, then to
`97663487...d77c5`. Full static validation comparison shows exactly 0.0 maximum
raw and calibrated probability difference across 5,422 rows. The sequential
state, policy selection, rules, policy config, model artifact, grids, budgets,
and objectives retain their authoritative hashes. The candidate table was born
at 2026-08-25T20:46:39+05:30, after both amendments; earlier stopped runs wrote
no candidate result. Exact timestamps for the strict-parity stop, intermediate
parity edit and uncached stop were not persisted, and are explicitly unavailable
rather than reconstructed. Full details are in
`artifacts/v2/validation_execution_amendment_001.json`.

## Ruff failure

Ruff failed with **205 violations**. Phase 2 lint did not pass. Source was not
retrospectively reformatted because validation had already been accessed and
the semantic source was freeze-hashed. This blocked snapshot is preserved.

## Coverage/environment limitation

**coverage unavailable in declared environment**

The initial environment lacked `pytest-cov`. Resolving the declared Python 3.11
environment then failed canonical collection because current Starlette requires
an undeclared `httpx2` package. An ad-hoc `--with httpx2` attempt is diagnostic,
not canonical, and produced no accepted coverage result. The frozen model also
cannot be loaded in that newly resolved Python 3.11 environment because it was
serialized by the available Python 3.13/scikit-learn runtime (`ModuleNotFoundError:
_loss`). Project dependency declarations and the blocked snapshot were not
changed; the transient `uv.lock` was moved to
`/tmp/card-testing-sentinel-coverage-uv.lock`.

## Deferred work

No Phase 3 work is authorized. No blind challenge may be generated or accessed.
Any continuation must be a separately named Phase 2B development iteration with
a fresh validation protocol. The current validation set is development evidence
because its results can influence future design.
