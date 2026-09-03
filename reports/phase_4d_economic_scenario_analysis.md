# Phase 4D — Economic Scenario Analysis

> **All monetary assumptions in this analysis are illustrative merchant-side scenario inputs. They are not measured Razorpay economics, production savings, or observed merchant losses.**

This is a synthetic, device-level expected-value analysis. It is not production economics. PBRSS NOT RESCORED; Model v3.1 unchanged; Policy v2 unchanged; no post-evaluation tuning.

## 1. Starting point

- Starting commit: `af01678b05e71661be2a5fc906d8c4213ec5baeb`
- Starting working tree: clean

## 2. Purpose

This analysis translates already-frozen PBRSS-v1 operating-point behavior into three reproducible merchant-side scenarios. It asks how the balance between surfaced attack value and legitimate-customer friction changes when attack prevalence or the assumed cost of a missed attack changes. It does not score a model or estimate observed merchant savings.

## 3. Evaluation basis and unit of analysis

The sole evaluation basis is the frozen synthetic PBRSS-v1 device-level result. The unit is a **device-level checkout actor**, also described as a device profile or risk opportunity. Fractional counts below are expected values, not partial people or observed transaction counts.

## 4. Frozen rates

| Frozen PBRSS-v1 metric | Rate |
|---|---:|
| Attack REVIEW+ | 96.40% |
| Attack BLOCK | 59.12% |
| Legitimate REVIEW+ | 20.72% |
| Legitimate BLOCK | 0.16% |
| Legitimate REVIEW-only (`REVIEW+ − BLOCK`) | 20.56% |

The calculator validates these values exactly and rejects a configuration that changes them. Attack REVIEW+ is the specified surfaced-attack rate. Attack BLOCK is preserved as frozen evidence but is not substituted for REVIEW+ in the economic protection formula.

## 5. Variables and formulas

For total device profiles `N`, attack prevalence `p`, missed-attack cost `C_attack`, genuine-review cost `C_review`, and genuine-hard-block cost `C_block`:

```text
A = N × p
L = N − A
A_surface = A × 0.964
A_missed = A × 0.036
L_review_only = L × 0.2056
L_block = L × 0.0016

V_protected = A_surface × C_attack
C_review_total = L_review_only × C_review
C_block_total = L_block × C_block
C_sentinel = A_missed × C_attack + C_review_total + C_block_total
C_no_sentinel = A × C_attack
V_net = C_no_sentinel − C_sentinel
      = V_protected − C_review_total − C_block_total
```

All calculations retain floating-point precision until human-readable presentation.

## 6. Quiet-day scenario

Assumptions: 100,000 device profiles, 0.10% attack prevalence, INR 2,000 missed-attack cost, INR 40 genuine-review cost, and INR 500 genuine-block cost.

| Result | Expected value |
|---|---:|
| Attack profiles | 100.00 |
| Legitimate profiles | 99,900.00 |
| Attack surfaced | 96.40 |
| Attack missed | 3.60 |
| Legitimate REVIEW-only | 20,539.44 |
| Legitimate hard-block | 159.84 |
| Protected attack value | INR 192,800.00 |
| No-Sentinel attack cost | INR 200,000.00 |
| Sentinel missed-attack cost | INR 7,200.00 |
| Review-friction cost | INR 821,577.60 |
| False-block cost | INR 79,920.00 |
| Total Sentinel cost | INR 908,697.60 |
| Net illustrative value | **INR −708,697.60** |

This scenario is below break-even. Under these assumptions, expected legitimate-customer friction dominates the protected attack value.

## 7. Active-attack-campaign scenario

Assumptions: 100,000 device profiles, 2.00% attack prevalence, INR 2,000 missed-attack cost, INR 40 genuine-review cost, and INR 500 genuine-block cost.

| Result | Expected value |
|---|---:|
| Attack profiles | 2,000.00 |
| Legitimate profiles | 98,000.00 |
| Attack surfaced | 1,928.00 |
| Attack missed | 72.00 |
| Legitimate REVIEW-only | 20,148.80 |
| Legitimate hard-block | 156.80 |
| Protected attack value | INR 3,856,000.00 |
| No-Sentinel attack cost | INR 4,000,000.00 |
| Sentinel missed-attack cost | INR 144,000.00 |
| Review-friction cost | INR 805,952.00 |
| False-block cost | INR 78,400.00 |
| Total Sentinel cost | INR 1,028,352.00 |
| Net illustrative value | **INR 2,971,648.00** |

This scenario is above break-even. Under these assumptions, the higher concentration of attack profiles makes the frozen operating point economically useful despite legitimate-profile friction.

## 8. High-value-merchant scenario

Assumptions: 100,000 device profiles, 0.50% attack prevalence, INR 10,000 missed-attack cost, INR 100 genuine-review cost, and INR 1,500 genuine-block cost.

| Result | Expected value |
|---|---:|
| Attack profiles | 500.00 |
| Legitimate profiles | 99,500.00 |
| Attack surfaced | 482.00 |
| Attack missed | 18.00 |
| Legitimate REVIEW-only | 20,457.20 |
| Legitimate hard-block | 159.20 |
| Protected attack value | INR 4,820,000.00 |
| No-Sentinel attack cost | INR 5,000,000.00 |
| Sentinel missed-attack cost | INR 180,000.00 |
| Review-friction cost | INR 2,045,720.00 |
| False-block cost | INR 238,800.00 |
| Total Sentinel cost | INR 2,464,520.00 |
| Net illustrative value | **INR 2,535,480.00** |

This scenario is above break-even. Under these inputs, a higher assumed cost per missed attack can justify greater review and hard-block friction.

## 9. Break-even prevalence

The exact implemented formula is:

```text
legit_friction_per_legit = 0.2056 × C_review + 0.0016 × C_block
attack_protection_per_attack = 0.964 × C_attack

p_break_even = legit_friction_per_legit
               / (attack_protection_per_attack + legit_friction_per_legit)
```

| Scenario | Break-even prevalence | Actual prevalence | Position |
|---|---:|---:|---|
| Quiet day | 0.465869% | 0.10% | Below |
| Active attack campaign | 0.465869% | 2.00% | Above |
| High-value merchant | 0.237608% | 0.50% | Above |

The test suite verifies the formula algebraically and substitutes the calculated prevalence back into the full scenario, where net value is numerically zero within floating-point tolerance.

## 10. No-Sentinel baseline

The only primary baseline assumes that every modeled attack profile proceeds without Sentinel intervention. Its cost is `A × C_attack`: INR 200,000 for quiet day, INR 4,000,000 for active attack campaign, and INR 5,000,000 for high-value merchant. No competitor behavior or economics are invented.

## 11. Interpretation

The same frozen fraud-control policy can be economically unattractive in low-risk traffic and valuable during active card-testing or when missed attacks are expensive. Under these illustrative assumptions, Sentinel has negative estimated net value on the quiet day and positive estimated net value in the active-campaign and high-value scenarios.

These comparisons expose the operating-point trade-off: high attack surfacing can protect more expected value as prevalence or attack cost rises, while the 20.56% genuine REVIEW-only rate creates substantial friction when attacks are scarce.

## 12. Limitations

- Monetary inputs are illustrative merchant assumptions, not measured Razorpay economics.
- PBRSS-v1 is a synthetic evaluation basis, not production traffic.
- Results apply to device profiles and expected-value opportunities, not transaction-level observations.
- REVIEW friction and hard-block costs are simplified scalar assumptions.
- Attack profiles are assumed to incur the full specified cost if not surfaced.
- The calculation does not model adaptation, recovery, manual-review capacity, latency, conversion heterogeneity, or uncertainty intervals.
- Positive estimated net value is scenario-dependent and is not a claim that Sentinel saves merchants money.
- `production_ready` remains false; this is not production economics.

## 13. Reproducibility and architecture

`configs/economic_scenarios.yaml` contains the frozen rates and scenario inputs. `scripts/run_economic_scenarios.py` validates the contract, performs deterministic arithmetic, and writes stable, key-sorted JSON to `artifacts/economics/phase_4d_economic_scenarios.json`.

Run:

```bash
.venv/bin/python scripts/run_economic_scenarios.py
```

The output contains no timestamp, random value, machine-dependent field, model score, or regenerated evaluation result. A unit test verifies byte-for-byte deterministic output.

## 14. Scoring and frozen-evidence boundary

The economic script imports only Python standard-library modules and PyYAML. It does not import the application package, model loader, model artifact, FeatureEngine, RiskService, NumPy, pandas, joblib, or scikit-learn. A static AST guard test enforces this boundary.

PBRSS NOT RESCORED. Model v3.1 unchanged. Policy v2 unchanged. No retraining, recalibration, threshold adjustment, policy modification, runtime modification, or post-evaluation tuning was performed.

## 15. Tests and verifiers

- Targeted economic tests: 18 passed
- Economic-script lint: passed
- Historical frozen-release verifier: passed (`frozen-v2-runtime`, 39 features,
  blind-v2 verdict `WEAK`, `post_blind_tuning: false`)
- Model v3.1 runtime verifier: passed (`postblind-v3.1-prototype-runtime`, 44
  features, PBRSS-v1 conclusion `MIXED`, `pbrss_rescored: false`,
  `production_ready: false`)
- Full repository test suite: 267 passed, 262 deselected, one non-blocking
  joblib physical-core discovery warning, 89% coverage
- Frozen artifact, source, README, and frontend integrity: unchanged
- `git diff --check`: passed
