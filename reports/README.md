# Card-Testing Sentinel — Evidence Index

This index identifies the evidence that describes the current Buildathon
submission. Phase numbers record development chronology; they do not indicate
which report is authoritative today.

## 1. Current system

```text
Dataset v4.1
→ 44 causal features / merchant-visible-causal-3.1
→ Model v3.1 / Histogram Gradient Boosting / hist_gb_2
→ sigmoid calibration
→ retained Policy v2
→ Razorpay Test Mode decision boundary
→ PBRSS-v1 distribution-shift stress evaluation
→ MIXED
→ production_ready=false
```

Dataset v4.1 contains 12,000 devices: 8,500 train and 3,500 held-out
development validation. PBRSS-v1 is a separate synthetic shifted stress suite
with 5,000 devices and 25% benchmark attack prevalence. Its result is consumed
and frozen; it was not used for post-stress tuning.

The current default verification runs 280 Python tests with 262 slow tests
deselected (542 collected total) and 69 frontend tests (31 legacy and 38 React).
The current local full-HTTP latency evidence covers 500 sequential prechecks:
p50 33.83 ms, p95 110.73 ms, p99 183.19 ms, and 0 errors. These are local
prototype measurements, not production guarantees.

## 2. Read these first

- [`phase_2_6_dataset_v4_1_audit.md`](phase_2_6_dataset_v4_1_audit.md) — dataset
  design, causal contract and leakage-group integrity.
- [`phase_2_6_model_v3_1_development.md`](phase_2_6_model_v3_1_development.md) —
  actor-safe candidate selection, calibration and held-out development results.
- [`phase_3c_pbrss_v1_one_score_evaluation.md`](phase_3c_pbrss_v1_one_score_evaluation.md)
  — canonical frozen shifted-stress result and its `MIXED` conclusion.
- [`phase_5b_1_real_razorpay_failure_lifecycle.md`](phase_5b_1_real_razorpay_failure_lifecycle.md)
  — real Test Mode failed-payment correlation and signed-webhook history.
- [`phase_4d_economic_scenario_analysis.md`](phase_4d_economic_scenario_analysis.md)
  — illustrative false-positive and merchant-cost trade-offs, including a
  negative low-prevalence scenario.
- [`phase_4c_razorpay_e2e_latency.md`](phase_4c_razorpay_e2e_latency.md) — current
  Razorpay order gating, lifecycle checks and local HTTP latency.
- [`phase_4b_v3_1_runtime_integration.md`](phase_4b_v3_1_runtime_integration.md) —
  active runtime binding and persistence integration.

## 3. Supporting current evidence

- [`phase_2_6_model_v3_1_ablations.md`](phase_2_6_model_v3_1_ablations.md) —
  controlled feature-family ablations.
- [`phase_4a_post_pbrss_diagnosis.md`](phase_4a_post_pbrss_diagnosis.md) — read-only
  diagnosis of shifted calibration and legitimate review friction.
- [`phase_11_policy_v2_report.md`](phase_11_policy_v2_report.md) — Policy v2
  selection provenance. It was selected under Model v2 and intentionally
  retained unchanged with active Model v3.1; `configs/runtime_v3_1.yaml` is the
  authoritative binding.
- [`phase_5a_final_figures.md`](phase_5a_final_figures.md) — provenance for
  evaluator-facing figures generated from committed aggregate artifacts.
- [`dependency_security_audit.md`](dependency_security_audit.md) — dated
  dependency-security evidence.

## 4. Historical frozen evaluation

Blind v2 was the earlier one-time evaluation of Model v2. Its `WEAK` result is
preserved intentionally and is not the active model or runtime evaluation.

- [`phase_12_blind_v2_freeze_report.md`](phase_12_blind_v2_freeze_report.md) —
  pre-evaluation freeze snapshot.
- [`phase_13_blind_v2_evaluation_report.md`](phase_13_blind_v2_evaluation_report.md)
  — frozen one-time Blind v2 result.
- [`post_blind_stress_v1_evaluation_report.md`](post_blind_stress_v1_evaluation_report.md)
  — generated pointer produced by the PBRSS one-score evaluator.

Frozen reports are historical evidence, not files to update with current prose.

## 5. Development and process history

The following are dated checkpoints rather than current system declarations:

- [`browser_verification.md`](browser_verification.md)
- [`final_hardening_baseline.md`](final_hardening_baseline.md)
- [`final_hardening_inventory.md`](final_hardening_inventory.md)
- [`repository_hygiene_report.md`](repository_hygiene_report.md)
- [`submission_cleanup_inventory.md`](submission_cleanup_inventory.md)

Historical test counts and environment details in these files describe their
own checkpoints and should not be read as current totals.

## 6. Superseded current-looking reports

- [`decision_path_benchmark.md`](decision_path_benchmark.md) — older benchmark;
  superseded for headline latency by `phase_4c_razorpay_e2e_latency.md`.
- [`final_hardening_report.md`](final_hardening_report.md) — earlier “final”
  checkpoint; superseded by the current runtime and verification evidence above.
- [`submission_cleanup_report.md`](submission_cleanup_report.md) — records the
  older Model v2/logistic/isotonic cleanup state; not the active stack.
- [`clean_install_verification.md`](clean_install_verification.md) and
  [`browser_verification.md`](browser_verification.md) — retained dated checks;
  current test counts and product behavior are defined by the active source,
  CI and the evidence listed in “Read these first.”

These reports are preserved to retain development provenance. Their historical
facts should not be rewritten to look current.

## 7. Frozen and hash-bound files

Do not edit these Markdown reports. Their exact bytes are bound by committed
result manifests:

- `reports/phase_13_blind_v2_evaluation_report.md`
- `reports/phase_3c_pbrss_v1_one_score_evaluation.md`
- `reports/post_blind_stress_v1_evaluation_report.md`

The first is bound by `artifacts/evaluation/blind_v2_result_hashes.json`; the
two PBRSS reports are bound by
`artifacts/evaluation/pbrss_v1_result_manifest.json`.
