# Phase 11 — Policy v2 Selection

Status: complete on Dataset v3 validation only. Blind v2 was neither generated nor
inspected. Model v2 was not retrained.

## 1. Starting repository state and inherited work

The repository started on `main` with a large, intentionally dirty working tree:
four historical generations and the Razorpay Test Mode work were present as a mix
of modified, deleted, renamed, and untracked files. No cleanup, merge, rename, or
deletion of that history was performed.

Claude had already created the parallel Policy v2 engine, v2 evidence/trust
vocabulary, validation-only vectorised candidate search, scenario/merchant/customer
segment reports, the preliminary Policy v2 artifact, and substantial action,
boundary, degraded-mode, isolation, and deterministic-selection tests. It had also
identified the brittle scenario caps, harmful campaign tolerance, zero selected-gate
suppression, and config-hash lifecycle bug.

This completion hardened the config writer, added independent config/artifact hash
verification and a policy-artifact sidecar, made the scenario guardrail uniform,
completed the threshold/campaign/evidence/delay diagnostics, regenerated the
selection artifacts, and expanded tests. Frozen inputs were not edited.

## 2. Hash lifecycle fix

The old pipeline hashed `configs/policy_v2.yaml` before reliably resolving the
selected values. Its replacement now performs this lifecycle:

1. select the policy;
2. replace every selected scalar in the existing commented YAML, including stale
   non-null values;
3. parse the file and assert every resolved value;
4. hash the final bytes on disk;
5. write that hash into the policy artifact;
6. independently reread and rehash the config;
7. hash the final policy artifact and write `operational_policy_v2.sha256`;
8. independently verify the sidecar against the artifact bytes.

An automated test deliberately writes a stale review threshold, runs the resolver,
and verifies that the resulting bytes and SHA-256 equal the final config.

## 3. Scenario-budget revision

The original draft used nine hand-authored family caps. For example,
`shared_network_customer block <= 0.01` on 166 validation devices allowed only one
blocked device. `cold_start_guest <= 0.005` on 402 devices allowed two. All 864
candidates failed, with small-cohort arithmetic being treated as evidence of policy
safety.

This was changed after that first zero-eligible search and before policy freeze.
The aggregate 1% block, 6% review+, 5:1 review-to-block, and 70% minimum attack
review+ constraints remain unchanged. Per-family constraints are now one uniform
stress guardrail: 6x the aggregate block cap and 5x the aggregate review cap, each
floored at two devices for small cohorts. There are no family-specific exceptions.

This is not presented as a confidence interval: the scenario cohorts are deliberately
enriched failure-mode tests rather than random samples from aggregate legitimate
traffic. The per-family ceilings only reject catastrophic concentration; the
aggregate caps are the actual friction budget. All family results remain visible
below, especially the high subscription-dunning friction.

## 4. Candidate grid and selection

The deterministic grid evaluated 864 candidates and found 36 eligible. It crossed:

- review thresholds: 0.50–0.75 in 0.05 steps;
- block thresholds: 0.75, 0.80, 0.85, 0.90;
- evidence counts: 1, 2, 3;
- evidence sets: `v1_like`, `v2_long_horizon`, `v2_full`;
- trust suppression: `none`, `moderate`;
- campaign increments: none or +0.05 review/+0.02 block.

Selection is constraint-first, then attack review+ recall, attack block recall,
detection speed, legitimate review friction, evidence breadth, and stronger evidence
count. Campaign tolerance has an additional dominance rule and cannot win for a tiny
friction change while losing meaningful detection.

Selected Policy v2:

- version/family: `validation-selected-v2` / `evidence_gated_v2`;
- review threshold: **0.75**;
- block threshold: **0.90**;
- evidence: **at least 2 signals from `v2_full`**;
- trust suppression: **none**;
- temporary block TTL: **3,600 seconds (60 minutes)**;
- campaign increments: **0.00 / 0.00**;
- degraded rule-only thresholds: review at rule score 4, block at 6.

The TTL candidates were 15, 30, and 60 minutes. TTL does not change this replay
because a block does not suppress later measured attempts. Sixty minutes was chosen
as an explainable prototype interval, not a Razorpay recommendation.

## 5. Evidence and degraded mode

The selected gate can use these explainable merchant-visible causal facts:

- v1-like: verified failures in 24h, decline streak, sessions in 24h, IP changes in
  24h, requests in 24h, and rapid retry after verified decline;
- long horizon: failures in 7d, active days in 7d, requests in 7d, irregular cadence;
- customer context: customer failures in 7d, plus multiple devices only when paired
  with customer failures.

Missing customer identity is neutral. `customer_id_present == 0` is never evidence.
Multiple devices alone are never block evidence.

When the model is unavailable, the policy uses the separate rule-only fallback and
emits `degraded_rules_only`. A degraded block has no ML-derived TTL. Invalid policy
state fails construction, and corrupt/model-contract-mismatched artifacts are not
silently scored by the runtime registry.

## 6. Threshold reports

Review reporting cuts (precision is conditional on this enriched synthetic benchmark,
not production precision; volume is attempts):

| Review cut | Attack review+ | Legit review+ | Precision | Attempts | Attempt rate |
|---:|---:|---:|---:|---:|---:|
| 0.40 | 95.51% | 14.58% | 78.27% | 4,790 | 38.57% |
| 0.45 | 95.30% | 12.52% | 79.66% | 4,581 | 36.88% |
| 0.50 | 94.23% | 10.92% | 80.98% | 4,374 | 35.22% |
| 0.55 | 94.23% | 9.33% | 82.32% | 4,190 | 33.74% |
| 0.60 | 93.38% | 8.16% | 83.20% | 4,030 | 32.45% |
| 0.65 | 91.67% | 7.27% | 83.89% | 3,824 | 30.79% |
| 0.70 | 89.96% | 6.14% | 84.93% | 3,583 | 28.85% |
| **0.75** | **87.39%** | **5.30%** | **86.08%** | **3,334** | **26.84%** |
| 0.80 | 83.55% | 4.31% | 87.76% | 2,999 | 24.15% |

Block cuts with the selected evidence design:

| Block cut | Attack block | Legit block | Score-only attempts | Evidence-qualified | Suppressed |
|---:|---:|---:|---:|---:|---:|
| 0.75 | 86.11% | 5.25% | 3,334 | 3,298 | 36 |
| 0.80 | 82.69% | 4.27% | 2,999 | 2,976 | 23 |
| 0.85 | 77.99% | 2.58% | 2,471 | 2,463 | 8 |
| **0.90** | **59.19%** | **0.89%** | **1,409** | **1,409** | **0** |

The lower block cuts fail the legitimate-block budget; 0.90 is the selected cut.

## 7. Aggregate outcome, model-only comparison, and delay

On 468 attack and 2,133 legitimate validation devices:

- attack review+: **87.39%** (409 devices);
- attack block: **59.19%** (277 devices);
- legitimate review+: **5.30%** (113 devices);
- legitimate block: **0.89%** (19 devices);
- median/p90 first review: **4 / 6.2 attempts**;
- median/p90 first block: **7 / 12 attempts**.

Cumulative attack detection:

| By attempt | Review+ | Block |
|---:|---:|---:|
| 1 | 4.49% | 0.64% |
| 2 | 19.87% | 4.70% |
| 3 | 29.27% | 9.62% |
| 5 | 72.44% | 16.03% |

At the selected cuts, model-only and final policy device behavior are identical:
0.75 yields 87.39% attack / 5.30% legitimate review+, while 0.90 yields 59.19%
attack / 0.89% legitimate block. Policy v2 therefore does not hide a Model v2 error
or demonstrate incremental protection on this validation set; it preserves an
evidence-gated architecture for distribution shift.

## 8. Campaign decision

The +0.05 review/+0.02 block tolerance changes legitimate review+ only from 5.30%
to 5.16% (0.14 percentage points) and does not change legitimate block (0.89%). It
reduces attack review+ from 87.39% to 86.11% and attack block from 59.19% to 52.78%
(6.41 percentage points). It is not retained.

## 9. Evidence-gate diagnosis

At score >= 0.90 there are 1,409 candidate attempts, all 1,409 already have at least
two `v2_full` evidence signals, and all are evidence-qualified. The selected gate
suppresses zero attempts, zero devices, zero legitimate blocks, and zero attack
blocks.

This occurs because the high-score validation tail already carries the broad v2
evidence vocabulary; the minimum observed evidence count is two. Dataset v3
validation therefore does not exercise the selected gate. This is not evidence of
a benefit and must not be reported as one. The gate is retained because Blind v1.1
previously prevented 12 legitimate blocks under shift, but Blind v1.1 was not reused
for selection or tuning here.

## 10. Attack families

| Family | Devices | Review+ | Block |
|---|---:|---:|---:|
| fast_burst | 28 | 85.71% | 67.86% |
| slow_drip | 50 | 92.00% | 66.00% |
| patient_tester_weeks | 37 | 89.19% | 45.95% |
| sparse_multiday_tester | 42 | 92.86% | 66.67% |
| cross_device_campaign | 164 | 82.32% | 46.95% |
| session_churn | 33 | 90.91% | 78.79% |
| successful_card_camouflage | 30 | 90.00% | 73.33% |
| warm_up_then_test | 24 | 79.17% | 45.83% |
| flash_sale_camouflage | 34 | 88.24% | 64.71% |
| merchant_typical_amounts | 26 | 100.00% | 84.62% |

At identical thresholds, v2-full versus v1-like evidence changes block recall by
**0.00pp** for patient testers (45.95% both), **+4.77pp** for sparse multiday
testers (61.90% to 66.67%), and **+39.02pp** for cross-device campaigns (7.93% to
46.95%). Long-horizon evidence helps sparse blocking slightly but does not show a
patient improvement. The patient problem remains unresolved; Blind v2 is the later
test. Cross-device evidence is useful on this development validation set.

## 11. Legitimate families

| Family | Devices | Review+ | Block |
|---|---:|---:|---:|
| subscription_dunning | 71 | 29.58% | 4.23% |
| network_retry_storm | 63 | 15.87% | 4.76% |
| persistent_card_problem_customer | 75 | 12.00% | 5.33% |
| household_shared_device | 107 | 8.41% | 0.00% |
| mobile_network_churn | 93 | 6.45% | 0.00% |
| shared_network_customer | 166 | 4.22% | 1.81% |
| returning_customer_multi_episode | 370 | 4.86% | 0.27% |
| multi_device_customer | 353 | 3.97% | 0.57% |
| cold_start_guest | 402 | 0.00% | 0.00% |

Subscription dunning remains the clearest friction weakness: nearly 30% review+ and
4.23% block within this deliberately enriched cohort. Network retry storms and
persistent card problems also concentrate blocks. Trust suppression did not win the
validation trade-off, so the final policy records `none`; these families must be
watched closely in Blind v2. Legitimate multi-device and guest cohorts remain safe.

## 12. Customer-ID segments

| Segment | Attack review+ | Attack block | Legit review+ | Legit block |
|---|---:|---:|---:|---:|
| customer ID absent | 81.90% | 52.38% | 1.21% | 0.00% |
| customer ID present | 88.98% | 61.16% | 7.12% | 1.29% |

Guests are not disproportionately blocked. Their lower detection is the expected
cost of neutral missing identity and is preferable to treating absence as evidence.

## 13. Artifacts and hashes

- Model v2: `0317cef5d310bc5d5d2ed55e755d995a34c54ad28df5ea780a36cb1e6fea2e3c`
- Model v2 metadata: `ebd146a7d9387b7f6eff3b0260a71b68cbad87ba4410a2fd6f424a74fc3c9c71`
- Feature Contract v2: `51bfa6604ed0486447ee16a43270f2092f0cac96b3ab0c2f0bad2748e8c28a38`
- Dataset v3 features_v2: `000c52aebbd0e2dbc58207289d6cba3db47ae4d771db3be251207dbb0365d51e`
- Final Policy v2 config: `92b0173e0ba073a9a20b7f09e5d0d82c9d40a52598cb9140ede36714a03c0052`
- Final Policy v2 artifact: `8e874ef83085b9bac063c3b0ac3044bb3c171071d00bf2db44c0390d944fe74c`

## 14. Preservation and verification

Direct manifest verification passed for Dataset v3 raw events
(`f02de8d4...`), labels (`daf0c116...`), and features_v2 (`000c52ae...`). The
consumed Blind v1.1 freeze verifier returned zero drift. Tests also verified Model
v1/Policy v1, Model v2, both feature contracts/engines, v1/v2 isolation, and artifact
bindings. No Blind v2 file exists.

Verification results:

- full Python suite: **440 passed** (one non-failing joblib CPU-count warning);
- targeted preservation/ML/policy suite: **152 passed**;
- Ruff lint: passed;
- Ruff format check: 138 files formatted;
- legacy frontend: **31 passed**;
- React frontend: **8 passed**;
- frontend production build: passed;
- Blind v1.1 freeze verification: passed, zero drift;
- final config and policy artifact independent SHA-256 checks: passed.

## 15. Freeze-readiness decision and remaining weaknesses

Model v2 + Policy v2 are safe to freeze as the **development-selected pair before
Blind v2**, because selection is deterministic and validation-only, bindings are
correct, frozen history is unchanged, aggregate budgets pass, and the test suite is
clean. This is not a production-performance claim.

Remaining weaknesses are material and explicit:

- no patient-attack improvement was demonstrated;
- warm-up and cross-device campaigns have only about 46% block recall;
- subscription dunning and genuine repeated-failure cohorts retain high friction;
- the selected evidence gate has zero incremental effect on Dataset v3 validation;
- guest attack detection is lower because missing identity correctly remains neutral;
- all metrics come from synthetic development data and are not fraud probabilities or
  production fraud-performance estimates.

Phase 11 stops here. Blind v2 remains a separate future phase.
