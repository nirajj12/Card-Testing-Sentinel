# Phase 12 — Blind v2 Specification, Generator, Validation, and Freeze

Status: **complete and frozen** on 2026-08-31. Blind v2 remains unevaluated and
unconsumed. Phase 13 was not started.

## 1. Blind v2 design goals

Blind v2 is an independently generated, temporally later, composition-shifted
benchmark for merchant-visible card-testing behavior. It emphasizes patient and
ultra-patient attacks, sparse multiday activity, imperfect cross-device linkage,
guest degradation, warm-up histories, and legitimate repeated-payment friction.
It is not derived by copying or perturbing Dataset v3 rows.

The generator emits raw causal events and separate device labels. Feature values
are produced only by FeatureEngine v2 as a dataset-validation projection. The
generation and validation dependency graph excludes model, policy, training,
evaluation, and policy-search modules.

## 2. Files created or changed

Phase 12 created:

- `configs/blind_v2.yaml`
- `docs/blind_v2_spec.md`
- `src/card_testing_sentinel/ml/blind_v2_generator.py`
- `src/card_testing_sentinel/ml/blind_v2_validation.py`
- `pipelines/generate_blind_v2.py`
- `pipelines/validate_blind_v2.py`
- `scripts/freeze_blind_v2.py`
- `tests/integration/test_blind_v2.py`
- `data/generated/blind_v2/raw_events.csv`
- `data/generated/blind_v2/labels.csv`
- `data/generated/blind_v2/features_v2.csv`
- `data/generated/blind_v2/manifest.json`
- `data/generated/blind_v2/reproducibility.json`
- `artifacts/evaluation/blind_v2_validation_report.json`
- `artifacts/evaluation/blind_v2_shift_report.csv`
- `artifacts/evaluation/blind_v2_freeze_manifest.json`
- `reports/phase_12_blind_v2_freeze_report.md`

Shared neutral event primitives, merchant mechanics, and FeatureEngine v2 were
reused without modification. No frozen historical version was cleaned up.

## 3. New seed and version

- Dataset version: `v2`
- Generator version: `blind-v2-generator-1`
- Behavioral seed: `817263541`
- Merchant seed: `44827193`
- Identity prefix: `bv2`
- RNG: NumPy `Generator(PCG64)`

## 4. Temporal window

- Configured start: 2027-06-01 00:00:00 UTC
- First event: 2027-06-01 00:52:04.542691 UTC
- Last event: 2028-02-09 16:24:54.356856 UTC
- Realized span: 253.648 days
- Dataset v3 last event used by validation: 2027-03-20 06:57:28.917236 UTC
- Strict separation: 72.746 days; no temporal overlap

## 5. Dataset size

- Devices: 4,000
- Actors: 2,763
- Observed customers: 2,525
- Raw events: 38,154
- Authorization requests/outcomes: 15,364 each
- Successful checkout events: 7,426
- Feature projection rows: 15,364

## 6. Attack fraction

- Attack devices: 800
- Legitimate devices: 3,200
- Attack-device fraction: 20.00%
- Attack-request fraction: 26.01%

The dataset deliberately enriches attacks for per-family diagnostics; the
fraction is not an estimate of production card-testing prevalence. All 800
labelled attack devices transact; there are no silent attack devices.

## 7. Merchant composition

All nine declared kinds and all 14 new merchant instances are realized.
`grocery_delivery` and `saas_tools` are the two new plausible Checkout kinds.

| Merchant kind | Instances | Devices | Device share |
|---|---:|---:|---:|
| digital_goods | 1 | 281 | 7.03% |
| education | 3 | 971 | 24.27% |
| electronics | 2 | 576 | 14.40% |
| flash_sale | 1 | 256 | 6.40% |
| grocery_delivery | 2 | 609 | 15.22% |
| saas_tools | 1 | 381 | 9.53% |
| small_ecommerce | 1 | 210 | 5.25% |
| subscription | 1 | 266 | 6.65% |
| travel | 2 | 450 | 11.25% |

## 8. Customer-ID presence

- Overall request presence: 63.78% (Dataset v3: 59.26%)
- Attack request presence: 53.88%
- Legitimate request presence: 67.26%
- Presence/absence attack-share gap: 11.15 percentage points
- `customer_id_present` best single-feature F1: 0.4128

Presence is shifted but remains within the requested plausible 50–65% overall
region, and it is not a deterministic label shortcut.

## 9. Attack families

All 14 declared attack families are realized:

| Family | Devices | Requests |
|---|---:|---:|
| burst_pause_burst_v2 | 24 | 284 |
| cross_device_partial | 133 | 378 |
| cross_device_strong | 184 | 407 |
| cross_device_weak_guest | 101 | 274 |
| fast_burst_v2 | 29 | 330 |
| merchant_normal_amount_attack | 30 | 275 |
| mixed_campaign_behavior | 24 | 268 |
| patient_tester_v2 | 46 | 160 |
| session_churn_v2 | 27 | 284 |
| sparse_multiday_v2 | 69 | 185 |
| success_camouflage_v2 | 28 | 304 |
| ultra_patient_v2 | 45 | 141 |
| variable_cadence_v2 | 29 | 313 |
| warm_up_then_attack_v2 | 31 | 393 |

## 10. Legitimate families

All 13 declared legitimate families are realized:

| Family | Devices | Requests |
|---|---:|---:|
| campaign_rush_v2 | 153 | 580 |
| campus_office_shared_network | 351 | 747 |
| dormant_returning_customer_v2 | 166 | 924 |
| high_value_retry_v2 | 120 | 417 |
| household_shared_ip | 410 | 527 |
| micro_payment_regular | 178 | 816 |
| mobile_network_churn_v2 | 164 | 685 |
| multi_device_customer_v2 | 616 | 1,163 |
| network_retry_storm_v2 | 116 | 811 |
| new_guest_checkout | 411 | 605 |
| persistent_card_problem_v2 | 100 | 676 |
| returning_long_history | 287 | 1,982 |
| subscription_dunning_v2 | 128 | 1,435 |

## 11. Patient and ultra-patient statistics

- Patient: 46 devices, 160 requests; 83 guest and 77 logged-in requests
- Ultra-patient: 45 devices, 141 requests; 102 guest and 39 logged-in requests
- Attempts per patient actor: minimum 3, median 5, maximum 8
- Patient requests with `requests_24h <= 2`: 100%
- Patient gaps are configured at 1–4 days; ultra-patient gaps at 2–6 days,
  with a 28% chance of a larger 7–18 day gap
- Normal merchant amounts dominate both families (86% and 90% configured weight)

These families deliberately restore low-short-window-velocity behavior without
making high failure counts universal.

## 12. Sparse-multiday statistics

- 69 devices and 185 requests
- Attempts configured at 4–8 across 1–4 day gaps
- Active days per sparse actor: minimum 4, median 6, maximum 8
- One to three devices per actor with partial linkage and 20–72% customer-ID
  presence, providing both thin device histories and accumulating actor history

## 13. Cross-device linkage statistics

- Cross-device attack actors: 146
- Strong cross-device family: 184 devices / 407 requests
- Partial cross-device family: 133 devices / 378 requests
- Weak guest family: 101 devices / 274 requests
- Dataset-wide linkage classes: 2,891 strong, 612 partial, 497 weak devices

The benchmark includes two to eight devices per relevant actor, mixed guest and
logged-in episodes, shared and rotating IP behavior, and deliberately incomplete
linkage rather than assuming every campaign is perfectly connected.

## 14. Guest and logged-in composition

Authorization-request rows by population and identity state:

- Attack guest: 1,843
- Attack logged in: 2,153
- Legitimate guest: 3,722
- Legitimate logged in: 7,646

All four required segments are non-empty. Guest-only attack behavior exists, but
guest status is not exclusive to attacks.

## 15. Legitimate multi-device overlap

- Legitimate multi-device actors: 484
- `multi_device_customer_v2`: 616 devices and 1,163 requests
- `customer_distinct_devices_7d` attack/legitimate overlap coefficient: 0.8133
- Its best single-feature F1 is 0.4128

Customer device multiplicity therefore does not become attack-only evidence.

## 16. Subscription-dunning behavior

- 128 devices and 1,435 requests/outcomes
- 727 declines and 708 approvals
- 122 devices have at least one decline; 124 have at least one approval; 118
  exhibit both outcomes
- Attempts are configured at 4–10 over 1–4 day gaps, with 1–7 prior warm-up
  attempts, varied tenure, and both subscription and SaaS merchants

This preserves realistic repeated failures and eventual success. Its size makes
the known friction risk measurable in Phase 13 without inspecting it now.

## 17. Shared-IP behavior

- Shared IPs: 95
- Requests from attacks on shared IPs: 938
- Requests from legitimate users on shared IPs: 3,621
- Household, campus/office, and mobile/CGNAT-like legitimate families coexist
  with shared and rotating attack IP behavior

## 18. Leakage and shortcut gates

All hard gates passed with no failures:

- Highest single-feature F1: 0.5480 (`failures_per_active_day_7d`), below 0.85
- Customer-ID-presence F1: 0.4128
- Required attack/legitimate feature overlap coefficients: 0.6052–0.9760
- Shuffled-label diagnostic: 0.5063, near chance. This is a dataset-only shuffled
  label sanity check, not Model v2 ROC-AUC.
- Every family and merchant kind realized; family dominance gate passed
- Zero labelled-but-unused attack devices
- Zero identity overlap with Dataset v3 and Blind v1.1 across event, request,
  device, customer, session, IP, and merchant IDs
- Raw authorization requests contain no outcome-only values, labels, populations,
  scenarios, actor IDs, or linkage classes
- Static AST dependency and branch checks found no forbidden model/policy path and
  no label- or population-conditioned branch in the actor generator

One realism warning is recorded: legitimate decline rate is 34.49%, slightly
above the configured 34% warning ceiling but below the 46% hard-fail ceiling.
Overall decline rate is 43.62%.

## 19. Dataset v3 versus Blind v2 distribution shift

Across 39 FeatureEngine v2 fields:

- Median PSI: 0.0792; maximum PSI: 0.9358
- Median KS: 0.0830
- Median overlap coefficient: 0.9169
- Customer-ID presence shifted from 59.26% to 63.78%
- Current amount median shifted from 1,125.08 to 4,320.94 and p90 from
  21,004.33 to 52,738.87 (PSI 0.2887, KS 0.2145, overlap 0.8890)
- Device-age PSI is 0.9358; customer-age PSI is 0.5285; active-day-count PSI is
  0.4269; gap-variability PSI is 0.3542
- Requests-7d median/p90 shifted from 3/10 to 2/6
- Merchant and scenario composition changed, including two new merchant kinds

The mixture is meaningfully different while broad feature overlap remains high.

## 20. Reproducibility

Two independent clean in-memory generations were performed. Raw events, labels,
FeatureEngine v2 projection, and manifest were byte-identical. The
reproducibility record states `runs: 2`, `clean_in_memory_generators: 2`, and
`byte_identical: true`.

## 21. Final hashes

Primary frozen outputs:

| Artifact | SHA-256 |
|---|---|
| specification | `e528eebfb200bd481cb9393d614cf6f650d8875615308d00276c853454f71378` |
| config | `bce8b8777d5c87329143ba0d989e0f8f3e232fa20b08d37acc491c22db9fbaf1` |
| generator | `4f17429f9b1b8bec92432385c9f7cd91d19ca6e7750f3902893769e327388532` |
| validator | `37a7108e612d2cc8ad854c9453fb54e7ff351d1a50d968494328f021c4a8f303` |
| raw events | `bfdc709863c89a6f496a95dd56cb86fd63290a7669817918bebe1165f79bf16d` |
| labels | `3a838bb77ee9137324f72ba544bc5edb5af3a3e3c5e46029304ff146135b4db7` |
| features v2 | `b661517f5dac5eda5e772e30ccd765dfa084d980e107957f055bda89e22d388f` |
| manifest | `3a4d96facab33f46bd31041a8da8b0db85d71528c8f8d08c38027927ba18aa95` |
| reproducibility record | `f0faccec4a5093a7ebd2849a92a1fd3c5620c962e504e25a22e19ec0d38b8f30` |
| validation report | `321a75cfa1ba43428e0efa3e56020927e2e95fbf25f504e714d32ac03b79681c` |
| shift report | `6f7b0ba8c96fc86c1c1fd7067b439a9e49918784df846e99f7f77b20fe299caf` |

The canonical mapping and all source/foundation hashes are in
`artifacts/evaluation/blind_v2_freeze_manifest.json`.

## 22. Preservation verification

Both pre- and post-phase verification report zero drift. Frozen anchors include:

| Preserved artifact | SHA-256 |
|---|---|
| Blind v1.1 freeze manifest | `d39ff0f9aed0bb82dd471e407df178d1d80f9f049d2cc4ffb566a1d813edbe7a` |
| Dataset v3 raw | `f02de8d4d186e4084cf9fd7104211655bf82960358f3517327e57e59392f49f8` |
| Dataset v3 labels | `daf0c116cd6d71a210d7a662743df0c9ce58c5d1a0c2c723b0cd2cf6a8f9e90d` |
| Dataset v3 features v2 | `000c52aebbd0e2dbc58207289d6cba3db47ae4d771db3be251207dbb0365d51e` |
| FeatureEngine v2 | `6aa29b5953bb4f6d875bd51848e81dbeece6d0a1939816cd8bc031b59b6901c0` |
| Feature Contract v2 artifact | `db9bbfdd78b315fd902e4a9f2ef05204ca5222522b921edbd3b2a64b077c1928` |
| Model v2 artifact | `0317cef5d310bc5d5d2ed55e755d995a34c54ad28df5ea780a36cb1e6fea2e3c` |
| Policy v2 config | `92b0173e0ba073a9a20b7f09e5d0d82c9d40a52598cb9140ede36714a03c0052` |
| Policy v2 artifact | `8e874ef83085b9bac063c3b0ac3044bb3c171071d00bf2db44c0390d944fe74c` |

The source revision history records three pre-evaluation validator/interface
corrections. Each occurred before the dataset freeze and explicitly records that
no model score, policy decision, or performance result was run.

## 23. Tests and lint

- Ruff formatting and lint: passed for all Phase 12 Python files
- Pre-freeze Blind v2 suite: 11 passed, one freeze-only test deselected
- Post-freeze Blind v2 plus Blind v1 freeze suite: 35 passed
- Blind v2 freeze verifier: zero drift
- Blind v1.1 freeze verifier: zero drift

No test command selected a model, policy, evaluation, or runtime-scoring test.

## 24. Remaining Blind v2 limitations

- It is synthetic and cannot establish production prevalence or capture every
  issuer, network, merchant, or adversarial adaptation.
- Legitimate decline rate is 34.49%, slightly above the warning band; this may
  make the benchmark friction-heavy even though it remains inside the hard gate.
- The largest shifts in device age and customer age are substantial; Phase 13
  interpretation should distinguish plausible temporal/composition shift from
  generalization failure.
- Weakly linked anonymous devices can only be connected through the
  merchant-visible signals that exist; unrelated guests intentionally remain
  unlinked.
- Per-family counts support diagnostics but smaller attack families still carry
  wider uncertainty than aggregate results.

## 25. Model v2 and Policy v2 evaluation confirmation

Model v2 was never loaded, invoked, or scored. Policy v2 was never instantiated
or run. No Model v2 scores, production-model performance metrics, policy outcomes,
or ALLOW/REVIEW/BLOCK decisions were generated or inspected. FeatureEngine v2 was
used solely for the permitted validation projection and dataset-only diagnostics.

## 26. Blind lifecycle state

The dataset manifest, reproducibility record, validation report, and freeze
manifest all agree:

```text
evaluated = false
consumed = false
contains_model_scores = false
contains_policy_decisions = false
```

## 27. One-time Phase 13 readiness

**Yes. Blind v2 is frozen and safe for one-time Phase 13 evaluation**, subject to
explicit approval. Its specification, sources, generated data, projection,
validation evidence, and preservation anchors are hashed; validation passed;
generation is byte-deterministic; and both lifecycle flags remain false.

Phase 13 must treat the first observed Model v2 or Policy v2 result as the single
evaluation and immediately mark Blind v2 consumed. No Phase 13 evaluation was
started here.
