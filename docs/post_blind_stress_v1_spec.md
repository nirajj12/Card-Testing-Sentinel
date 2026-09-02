# Post-Blind Remediation Stress Suite v1 Specification

## 1. Philosophical Grounding: Why This Is NOT "Blind v3"

In machine learning methodology, **blind evaluation integrity cannot be reset once consumed**.
The evaluation of `blind-v2` on August 31, 2026, revealed specific vulnerabilities in Card-Testing Sentinel:
- 79.2% miss rate on `cross_device_weak_guest`
- 72.7% false block rate on `subscription_dunning_v2`
- 34.0% false block rate on `persistent_card_problem_v2`
- Severe calibration drift under feature shifts (PSI up to 0.9358)

Because these findings directly inform the redesign of Dataset v4, FeatureEngineV3, and Model v3, **any future evaluation designed by this team is contaminated by knowledge of what failed.**
Calling a new test suite "Blind v3" would be scientifically dishonest and create a false impression of independent validation.

Therefore, this benchmark is formally designated:
$$\textbf{Post-Blind Remediation Stress Suite v1 (PBRSS-v1)}$$

It serves not as an unbiased general blind test, but as an **adversarial stress suite** designed to rigorously test whether the specific remediations engineered in Phase 2 hold up under deliberate distribution shifts without creating new pathological failures.

---

## 2. Technical Profile & Structural Shifts

PBRSS-v1 must differ systematically from Dataset v4 development data to ensure that Model v3 has not merely overfitted the new development scenarios.

| Dimension | Dataset v4 (Development) | Post-Blind Remediation Stress Suite v1 | Deliberate Distribution Shift |
|---|---|---|---|
| **Spec Version** | `v4-postblind-draft` | `pbrss-v1-frozen-spec` | Independent configuration |
| **Generator Version** | `dataset-v4-generator-1` | `pbrss-v1-generator-1` | Distinct random streams |
| **Random Seed** | `918273645` | `773829104` | Fully disjoint PRNG stream |
| **Population Size** | 12,000 devices (~50,000 requests) | **5,000 devices (~20,000 requests)** | High-density stress sample |
| **Attack Device Fraction**| 18.0% | **25.0%** | Higher attack density stress |
| **Merchant Archetypes** | 6 archetypes (20 merchants) | **8 archetypes (16 new merchants)** | Adds 2 unseen merchant categories |
| **Unseen Archetypes** | None | **B2B Wholesale** & **Donation/Charity Platform** | Evaluates out-of-domain merchant transfer |
| **Guest Checkout Rate** | 40% – 50% | **55% – 65%** | Higher unauthenticated friction stress |
| **Timing Jitter** | Standard log-normal delay | **Bursty Pareto-distributed network delays** | Flaky cellular & carrier delay shifts |
| **Attack Cadence Jitter** | Predeclared ranges | **Asymmetric randomized pauses (1h to 48h)** | Stress tests long-horizon memory limits |

---

## 3. Held-Out Scenario Families & Parameter Extrapolations

To guarantee genuine stress generalization, PBRSS-v1 introduces scenario families and parameter regimes that are **explicitly forbidden** from Dataset v4 development data:

### 3.1 Completely Held-Out Scenario Families
1. **`stealth_low_amount_drip` (Unseen Attack)**:
   - Attacker tests stolen cards at ₹1.00 – ₹5.00 intervals with inter-attempt gaps of 18 to 36 hours across 10 days. Dwells below standard daily velocity windows.
2. **`hybrid_credential_stuffing_probe` (Unseen Attack)**:
   - Attacker attempts login with compromised user/password, immediately attempts card checkout with stolen card, and switches user on decline.
3. **`charity_micro_donation_spike` (Unseen Legitimate)**:
   - A viral fundraising appeal where 500 legitimate first-time guest donors make ₹50 – ₹100 donations within 2 hours, many with rapid retries after 3DS drops.
4. **`b2b_multi_corporate_card` (Unseen Legitimate)**:
   - Procurement employee testing 4 different corporate procurement cards for a ₹120,000 invoice where individual cards encounter credit limit blocks.

### 3.2 Parameter Extrapolations (Stress Bounds)
- **Retry Jitter**: Inter-attempt retry intervals compressed to 1.5 – 3.0 seconds (testing race conditions) and expanded to 7 – 14 days (testing long-horizon decay).
- **Subnet Sharing Density**: Cellular CGNAT simulation increased to 80 devices per `/24` IPv4 subnet.

---

## 4. Governance, Freeze Protocol & One-Score Evaluation Policy

To prevent metric tuning and overfitting on the stress suite, PBRSS-v1 is governed by the same strict one-look protocols pioneered in Phase 12/13:

### 4.1 Generation & Freeze Workflow
```text
Step 1: Commit configs/post_blind_stress_v1.yaml
Step 2: Generate data/generated/pbrss_v1_raw.csv & data/generated/pbrss_v1_features.csv
Step 3: Generate data/generated/pbrss_v1_labels.csv
Step 4: Compute SHA-256 digests for raw data, feature matrices, labels, and generator code
Step 5: Write artifacts/evaluation/pbrss_v1_freeze_manifest.json
Step 6: LOCK AND FREEZE. Model development proceeds without reading PBRSS-v1 labels or scores.
```

### 4.2 The One-Score Evaluation Policy
1. **Single Authorized Evaluation**:
   - PBRSS-v1 is evaluated **exactly once** at the conclusion of Phase 2 model training.
   - It is scored only when Model v3 and Policy v3 have been frozen and verified on development cross-validation.
2. **Immediate Consumption Record**:
   - The evaluation runner (`pipelines/evaluate_pbrss_v1_once.py`) writes an authoritative consumption record (`pbrss_v1_consumption.json`) containing the timestamp and git commit sha before reporting metrics.
3. **Strict Prohibition on Post-Stress Tuning**:
   - If Model v3 fails any target on PBRSS-v1, the failure is reported openly in the final submission report. Retraining Model v3 against PBRSS-v1 errors is strictly prohibited.

---

## 5. Artifact Manifest & Reporting Deliverables

The stress evaluation will generate and commit the following authoritative artifacts:
- `artifacts/evaluation/pbrss_v1_metrics.json` (aggregate PR-AUC, ROC-AUC, Brier, ECE, Review+, Block rates)
- `artifacts/evaluation/pbrss_v1_family_metrics.csv` (breakdown across every individual scenario family)
- `artifacts/evaluation/pbrss_v1_detection_delay.json` (cumulative detection at attempt 1, 2, 3, 5)
- `artifacts/evaluation/pbrss_v1_calibration.csv` (10 equal-width reliability bins)
- `artifacts/evaluation/pbrss_v1_counterfactual.json` (Counterfactual Pair Ordering Accuracy)
- `reports/post_blind_stress_v1_evaluation_report.md` (comprehensive audit narrative)
