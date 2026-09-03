# Phase 3C — PBRSS-v1 One-Score Evaluation

## 1. Evaluation status

**COMPLETE.** The one and only authorized Model v3.1 evaluation on frozen PBRSS-v1 completed successfully. The evaluator exited successfully, created the atomic consumption record, and produced all six authoritative outputs.

## 2. Frozen lineage

| Checkpoint | Commit |
|---|---|
| Model v3.1 freeze | `1c9dab4ed2902b4207e6758f1c929fee1b8a08dc` |
| Corrected PBRSS machinery freeze | `5941689847ed7a44f2db02fc86607dc619e6167c` |
| PBRSS-v1 dataset freeze / score-time HEAD | `de7281934363310fa71c946d9192ff9bb8aaaf87` |

The scored stack was frozen Model v3.1, Feature Contract v3.1 (`merchant-visible-causal-3.1`), sigmoid calibration, Policy v2 (`validation-selected-v2`), and the frozen PBRSS-v1 dataset.

## 3. One-score governance

Before scoring, HEAD matched the dataset-freeze commit, the working tree was clean, consumption and score outputs were absent, all declared dataset/foundation/source hashes matched, and the safe preflight returned `status: passed`. The authorized command was executed exactly once:

```text
.venv/bin/python pipelines/evaluate_pbrss_v1_once.py
```

No regeneration, retraining, recalibration, threshold selection, feature change, policy change, or retry occurred.

## 4. Consumption record

| Field | Frozen value |
|---|---|
| Status | `consumed` |
| Suite | `post-blind-remediation-stress-v1` |
| Consumed at | `2026-09-03T01:38:05.731601+00:00` |
| Scoring started | `2026-09-03T01:38:05.600494+00:00` |
| Git commit | `de7281934363310fa71c946d9192ff9bb8aaaf87` |
| Model | `model-v3.1` |
| Feature contract | `merchant-visible-causal-3.1` |
| Calibration | `sigmoid` |
| Policy | `validation-selected-v2` |
| Post-stress tuning | `false` |

## 5. Dataset identity and counts

| Measure | Count |
|---|---:|
| Events | 52,462 |
| Authorization requests | 20,714 |
| Devices | 5,000 |
| Attack devices | 1,250 |
| Legitimate devices | 3,750 |
| Merchants | 16 |

The six frozen scenario populations total 5,000 devices: 250 stealth low-amount drip, 250 hybrid credential-stuffing probe, 750 mixed-card probe, 500 charity micro-donation spike, 250 B2B multi-corporate-card, and 3,000 ordinary checkout.

## 6. Aggregate metrics

| Metric | Frozen PBRSS-v1 result |
|---|---:|
| PR-AUC | 0.6469762178 |
| ROC-AUC | 0.7261889167 |
| Brier | 0.1560370150 |
| ECE | 0.1406790070 |
| Log loss | 0.6538091381 |

These are device-weighted synthetic-stress results. Generic accuracy is intentionally not used as a headline metric.

## 7. Product policy outcomes

| Outcome | Frozen Policy v2 result |
|---|---:|
| Attack REVIEW+ | 96.40% |
| Attack BLOCK | 59.12% |
| Legitimate REVIEW+ | 20.72% |
| Legitimate BLOCK | 0.16% |
| False positives per 10,000 legitimate devices | 2,072 |

In this prototype, **REVIEW means Sentinel locally suppresses order creation and returns a review decision state**. It does not mean Razorpay manual review, 3DS, OTP, or issuer verification.

## 8. Scenario-by-scenario results

| Scenario | Population | N devices | REVIEW+ | BLOCK |
|---|---|---:|---:|---:|
| `stealth_low_amount_drip` | Attack | 250 | 100.00% | 100.00% |
| `hybrid_credential_stuffing_probe` | Attack | 250 | 100.00% | 60.80% |
| `mixed_card_probe` | Attack | 750 | 94.00% | 44.93% |
| `charity_micro_donation_spike` | Legitimate | 500 | 0.00% | 0.00% |
| `b2b_multi_corporate_card` | Legitimate | 250 | 7.20% | 0.80% |
| `ordinary_checkout` | Legitimate | 3,000 | 25.30% | 0.13% |

Attack coverage is consistently high across the three declared attack families. The principal product weakness is elevated review friction on ordinary checkout; B2B traffic also exceeds the 6% historical primary legitimate REVIEW+ gate and has a 0.80% block rate.

## 9. Detection delay

| Detection statistic | Frozen result |
|---|---:|
| Attack detected by attempt 1 | 23.20% |
| Attack detected by attempt 2 | 25.20% |
| Attack detected by attempt 3 | 92.16% |
| Attack detected by attempt 5 | 96.40% |
| Median first detection attempt | 3 |
| P90 first detection attempt | 3 |

The largest gain occurs at attempt 3: early detection is limited through attempt 2, then reaches 92.16% by attempt 3.

## 10. Calibration

Brier is **0.1560370150** and ECE is **0.1406790070**. The frozen reliability bins are:

| Score bin | Device weight | Mean predicted | Observed rate |
|---|---:|---:|---:|
| [0.0, 0.1) | 3524.2922 | 0.0158 | 0.1454 |
| [0.1, 0.2) | 250.6333 | 0.1394 | 0.0756 |
| [0.2, 0.3) | 138.2556 | 0.2474 | 0.0890 |
| [0.3, 0.4) | 35.8000 | 0.3387 | 0.1597 |
| [0.4, 0.5) | 37.3000 | 0.4502 | 0.2560 |
| [0.5, 0.6) | 43.9121 | 0.5489 | 0.2322 |
| [0.6, 0.7) | 45.8333 | 0.6561 | 0.2375 |
| [0.7, 0.8) | 52.1843 | 0.7481 | 0.4162 |
| [0.8, 0.9) | 179.5628 | 0.8511 | 0.5095 |
| [0.9, 1.0] | 692.2264 | 0.9245 | 0.8042 |

The dominant low-score bin underpredicts the observed positive rate, while every higher bin overpredicts it. This is substantial calibration error under PBRSS-v1. No recalibration was performed.

## 11. Counterfactual result

**No PBRSS-v1 counterfactual pair benchmark was present.** The frozen artifact records `pairs: 0` and `ordering_accuracy: null`; this is not treated as an evaluation failure.

## 12. Reference-gate results

| Reference gate | Result | Status |
|---|---:|---|
| Historical primary: Attack REVIEW+ >= 70% | 96.40% | **PASS** |
| Historical primary: Legitimate REVIEW+ <= 6% | 20.72% | **FAIL** |
| Historical primary: Legitimate BLOCK <= 1% | 0.16% | **PASS** |
| Development stretch: Attack REVIEW+ >= 80% | 96.40% | **PASS** |
| Development stretch: Legitimate REVIEW+ <= 4% | 20.72% | **FAIL** |
| Development stretch: Legitimate BLOCK <= 0.5% | 0.16% | **PASS** |
| Development stretch: PR-AUC >= 0.70 | 0.646976 | **FAIL** |
| Development stretch: ROC-AUC >= 0.85 | 0.726189 | **FAIL** |
| Development stretch: Brier <= 0.08 | 0.156037 | **FAIL** |
| Development stretch: ECE <= 0.03 | 0.140679 | **FAIL** |

These are reporting references only. Nothing was changed to satisfy them.

## 13. Historical Blind-v2 contextual comparison

Blind v2 and PBRSS-v1 are **different datasets**. This is a directional engineering comparison, not a matched-dataset causal comparison and not a claim of improvement on the same benchmark.

| Metric | Historical Blind v2 | PBRSS-v1 |
|---|---:|---:|
| Attack REVIEW+ | 70.5000% | 96.4000% |
| Attack BLOCK | 34.1250% | 59.1200% |
| Legitimate REVIEW+ | 14.9062% | 20.7200% |
| Legitimate BLOCK | 5.0937% | 0.1600% |
| PR-AUC | 0.487127 | 0.646976 |
| ROC-AUC | 0.735120 | 0.726189 |
| Brier | 0.152069 | 0.156037 |
| ECE | 0.117139 | 0.140679 |

Relative to the historical Blind-v2 failure, the separately specified PBRSS-v1 stress suite produced higher attack REVIEW+ and BLOCK, much lower legitimate BLOCK, and higher PR-AUC. It also produced worse legitimate REVIEW+ friction, slightly lower ROC-AUC, and worse Brier/ECE calibration. The evidence is therefore mixed rather than uniformly stronger.

## 14. Development-v4.1 versus PBRSS caution

Development-v4.1 validation and PBRSS-v1 are different synthetic datasets with different distributions and purposes. Development-v4.1 reported 93.49% attack REVIEW+, 3.14% legitimate REVIEW+, 0.14% legitimate BLOCK, 0.9169 PR-AUC, 0.9693 ROC-AUC, 0.0410 Brier, and 0.0214 ECE. PBRSS-v1 cannot be treated as a matched holdout from that distribution, so the difference must not be described as a controlled generalization gap or attributed to a single cause. It shows that the strong development results did not transfer uniformly to the predeclared remediation stress suite.

## 15. Limitations

- PBRSS-v1 is synthetic stress evidence, not production Razorpay fraud performance.
- It is not an independent real-world benchmark or a fresh blind test.
- It does not prove production generalization.
- The scenario mix and 25% attack prevalence are benchmark design properties, not production prevalence estimates.
- Family rates, especially the 250-device scenarios, are finite synthetic-cohort estimates.
- No PBRSS-v1 counterfactual pair benchmark was included.
- The result may be used for honest reporting, but not for post-PBRSS model or policy tuning.

## 16. Frozen conclusion

**Evaluation conclusion: MIXED.** Model v3.1 showed substantially stronger attack REVIEW+ behavior on the predeclared post-Blind remediation stress suite and kept aggregate legitimate BLOCK low. However, legitimate REVIEW+ is 20.72%, PR-AUC and ROC-AUC miss their references, Brier and ECE show poor calibration, and ordinary checkout has 25.30% REVIEW+ friction. These frozen metrics do not support a production-readiness claim.

**NO POST-PBRSS MODEL TUNING PERFORMED**

**PBRSS-v1 IS NOW CONSUMED**

**MODEL v3.1 EVALUATION IS FROZEN**
