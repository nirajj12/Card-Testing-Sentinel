# Phase 4A — Post-PBRSS Diagnosis

## 1. Scope and boundary

PBRSS-v1 is consumed. This phase is diagnosis only: **no rescore, no tuning, and no model, calibration, feature, policy, threshold, dataset, runtime, or evaluation-artifact change** was performed. The analysis reads the frozen evaluation artifacts and compares existing feature-table rows descriptively. It never loads Model v3.1, calls `score_frame`, `predict`, or `predict_proba`, or recreates REVIEW/BLOCK decisions.

Three epistemic levels govern this report:

- **OBSERVED:** measured directly from frozen artifacts or the two frozen feature tables.
- **SUPPORTED HYPOTHESIS:** a measured feature shift aligns with sensitivity already observed in the frozen Phase 2.6 development ablations.
- **NOT PROVEN:** exact per-device attribution is unavailable because consumed PBRSS-v1 was deliberately not rescored.

## 2. Frozen evaluation finding

The consumed PBRSS-v1 evaluation recorded 96.40% attack REVIEW+, 59.12% attack BLOCK, 20.72% legitimate REVIEW+, and 0.16% legitimate BLOCK. The evidence is mixed: attack coverage is high and hard legitimate blocking is low, but REVIEW locally suppresses order creation, so the legitimate REVIEW+ rate represents substantial payment friction.

## 3. Main failure concentration

| PBRSS legitimate scenario | Devices | REVIEW+ | BLOCK |
|---|---:|---:|---:|
| `ordinary_checkout` | 3,000 | **25.30%** | 0.13% |
| `charity_micro_donation_spike` | 500 | 0.00% | 0.00% |
| `b2b_multi_corporate_card` | 250 | 7.20% | 0.80% |

The aggregate friction is concentrated in ordinary checkout. Charity's clean outcome and B2B's lower REVIEW+ show that no single generic property such as retries, declines, shared IP, or multiple cards can be declared sufficient from scenario labels alone.

## 4. Feature-distribution shift analysis

### Method

The comparison uses all 16,325 request rows from the frozen Dataset v4.1 legitimate validation population and all 12,082 frozen PBRSS ordinary-checkout request rows. This is a request-row descriptive comparison; it is not a new device score or performance metric. For each of the 44 contract features, the companion CSV records mean, median, sample standard deviation, P10, P25, P75, P90, and zero fraction for both populations, plus contextual charity, B2B, and PBRSS-attack means/medians.

PSI uses development legitimate validation as the reference, reference-decile quantiles, cuts placed between unique quantile values to preserve discrete/binary categories, open-ended outer bins, and a fixed `1e-6` empty-bin floor. KS is a second descriptive distance. PSI/KS rank covariate shift only; neither is model importance or causal attribution. Zero has feature-specific semantics, including neutral missing-history values, so each interpretation follows the implemented FeatureEngine definition.

### Top 15 shifted causal features

| Feature | Existing feature family | Development legitimate mean / median | PBRSS ordinary mean / median | PSI | KS | Direction |
|---|---|---:|---:|---:|---:|---|
| `device_age_seconds` | Identity / continuity | 8,703,738.48 / 2,592,000.00 | 45,619.61 / 7.53 | 6.854 | 0.585 | Lower |
| `seconds_since_last_payment` | Failure / success history | 1,071,890.28 / 143,509.35 | 30,771.91 / 4.46 | 6.820 | 0.535 | Lower |
| `customer_age_seconds` | Identity / continuity | 8,382,688.02 / 2,592,000.00 | 18,277.31 / 0.00 | 6.375 | 0.555 | Lower |
| `seconds_since_last_success` | Identity / continuity | 1,073,631.12 / 145,927.71 | 31,240.55 / 3.81 | 6.073 | 0.533 | Lower |
| `seconds_since_last_request` | Velocity / retry | 946,140.58 / 77,701.22 | 30,771.91 / 4.46 | 5.131 | 0.486 | Lower |
| `sessions_24h` | Session churn | 1.256 / 1.000 | 1.000 / 1.000 | 2.204 | 0.181 | Lower |
| `median_gap_between_attempts` | Temporal shape | 276,226.11 / 0.00 | 222.36 / 3.43 | 2.057 | 0.239 | Lower |
| `ip_changes_24h` | IP / shared network | 0.158 / 0.000 | 0.000 / 0.000 | 1.462 | 0.129 | Lower |
| `session_churn_rate_24h` | Session churn | 0.872 / 1.000 | 0.544 / 0.500 | 1.400 | 0.523 | Lower |
| `amount_variation_24h` | Amount / transaction | 2,354.39 / 0.00 | 8,356.07 / 173.82 | 1.175 | 0.516 | Higher |
| `prior_payments_24h` | Failure / success history | 0.687 / 0.000 | 1.448 / 1.000 | 1.125 | 0.461 | Higher |
| `ip_rotation_ratio_24h` | IP / shared network | 0.847 / 1.000 | 0.544 / 0.500 | 1.043 | 0.484 | Lower |
| `customer_successful_checkouts_30d` | Identity / continuity | 0.672 / 1.000 | 0.206 / 0.000 | 1.038 | 0.435 | Lower |
| `requests_24h` | Velocity / retry | 1.785 / 1.000 | 2.448 / 2.000 | 0.850 | 0.388 | Higher |
| `distinct_card_last4_7d` | Card diversity / switching | 0.415 / 0.000 | 0.719 / 1.000 | 0.801 | 0.335 | Higher |

At the family level, median PSI is highest for session churn (1.400), identity/continuity (1.038), velocity/retry (0.739), IP/network (0.712), and card diversity (0.635). The IP-family rank is driven mainly by an absence of IP changes and lower rotation ratio, not by multi-device shared-IP crowding.

The complete 44-feature table is `artifacts/analysis/phase_4a_ordinary_checkout_feature_shift.csv`.

## 5. Failure/retry history findings

**OBSERVED:** PBRSS ordinary checkout does not simply contain larger failure counts. Mean `recent_failures_24h` is slightly lower than development legitimate traffic (0.587 versus 0.609), and mean `decline_streak` is also lower (0.464 versus 0.616). Therefore, “ordinary checkout had more raw declines” is not supported.

The shape of outcome history is nevertheless harder and more broadly exposed:

- The zero fraction for `recent_failures_24h` falls from 78.74% to 60.06%; failures occur on more request rows even though the mean count is slightly lower.
- Mean `failure_ratio_24h` rises from 0.204 to 0.293.
- Mean `retry_after_decline_ratio_24h` rises from 0.073 to 0.161.
- Mean `prior_payments_24h` rises from 0.687 to 1.448, with its zero fraction falling from 74.19% to 28.12%.
- Mean device `successful_checkouts_30d` falls from 0.925 to 0.536, and its zero fraction rises from 40.48% to 75.14%.
- Mean customer `successful_checkouts_30d` falls from 0.672 to 0.206, and its zero fraction rises from 46.62% to 90.13%.

**SUPPORTED HYPOTHESIS:** ordinary checkout presents more frequent exposure to recent payment outcomes and retry behavior but much less protective successful-checkout continuity. This overlapping failure/retry-with-limited-trust regime plausibly contributes to the shifted behavior.

**NOT PROVEN:** these features cannot be assigned as the cause of any particular REVIEW decision without recreating forbidden per-row scores.

## 6. Velocity, session, and timing findings

**OBSERVED:** ordinary checkout has denser repeat activity than development legitimate validation traffic:

- `requests_10s`: mean 1.648 versus 1.160.
- `requests_60s`: mean 1.744 versus 1.312.
- `requests_5m`: mean 1.745 versus 1.486.
- `requests_24h`: mean 2.448 / median 2 versus mean 1.785 / median 1.
- `seconds_since_last_request`: median 4.46 seconds versus 77,701.22 seconds.
- `sessions_24h` is exactly 1 throughout PBRSS ordinary rows, versus mean 1.256 in development legitimate rows.
- `session_churn_rate_24h` is 0.544 / median 0.5 versus 0.872 / median 1.0, reflecting more attempts within one session rather than more distinct sessions.

The ordinary distribution is therefore retry-dense but not session-churn-heavy. The median `session_age_seconds` is only 7.53 seconds, although a long tail raises its mean; robust statistics are essential here.

The frozen detection artifact independently shows only 23.20% attack detection by attempt 1 and 25.20% by attempt 2, rising to 92.16% by attempt 3 and 96.40% by attempt 5, with median and P90 first detection at attempt 3. This indicates strong reliance on accumulated behavioral history: useful for avoiding premature hard action, but limited for the earliest attempts.

## 7. Identity/trust findings

**OBSERVED:** identity and established-history distributions shift materially:

- `customer_id_present` falls from 79.06% to 39.26% (PSI 0.702; KS 0.398).
- Median `customer_age_seconds` falls from 30 days to 0; 70.49% of ordinary rows have the neutral zero value versus 32.98% in development legitimate traffic.
- Median `device_age_seconds` falls from 30 days to 7.53 seconds.
- The first-attempt/new-device fraction rises only from 17.58% to 24.83%, so the age collapse is not explained solely by more first requests; histories are also much less established between attempts.
- Customer and device successful-checkout histories are substantially thinner, as recorded above.

**SUPPORTED HYPOTHESIS:** reduced identity/continuity and successful-history insulation is a plausible contributor. Frozen Phase 2.6 evidence supports sensitivity in this direction: removing `customer_id_present` increased development legitimate REVIEW+ from 3.14% to 4.22% and reduced PR-AUC by 0.0120; removing the five trust/continuity features modestly increased legitimate REVIEW+ and BLOCK.

**NOT PROVEN:** missing customer identity alone did not cause PBRSS friction. It is neutral when missing, it is absent from policy evidence codes, and Phase 2.6 showed it acts as useful legitimate context rather than an attack gate.

## 8. Card/entity relationship findings

**OBSERVED:** ordinary checkout has more prior card diversity at the request-row level:

- `distinct_card_last4_7d`: mean 0.719 / median 1 versus 0.415 / median 0.
- `distinct_card_networks_7d`: mean 0.719 / median 1 versus 0.404 / median 0.
- `card_diversity_ratio_7d`: mean 0.263 / median 0.333 versus 0.135 / median 0.
- `card_change_after_decline_7d` is exactly 0 in ordinary checkout, compared with mean 0.020 in development legitimate traffic.

Customer relationship shifts are smaller: `customer_distinct_devices_7d` has PSI 0.039 and `customer_failures_7d` PSI 0.181. B2B has substantially higher card/customer-relationship values than ordinary checkout but only 7.20% REVIEW+, again ruling out a one-dimensional card-count explanation.

**SUPPORTED HYPOTHESIS:** card context participates in a broader multivariate shift, while established customer/entity continuity is weaker.

**NOT PROVEN:** the two card-ratio features are not established as the primary mechanism. Frozen Phase 2.6 ablations found that dropping either or both did not recreate the development dunning failure; the broader six-feature relationship/entity removal was materially harmful, but that prior sensitivity does not attribute current PBRSS decisions.

## 9. Network/shared-IP findings

**OBSERVED:** ordinary checkout does not show CGNAT-like multi-device crowding:

- `requests_per_ip_5m` rises moderately from mean 1.409 to 1.745.
- `devices_per_ip_24h` is effectively unchanged and slightly lower: mean 1.010 versus 1.170, median 1 in both.
- `ip_changes_24h` is 0 throughout ordinary checkout.
- Lower `ip_rotation_ratio_24h` (0.544 versus 0.847) follows repeated same-IP attempts, not shared-IP device spread.

For context, charity traffic has mean `devices_per_ip_24h` 38.96 and `requests_per_ip_5m` 10.43 yet frozen REVIEW+ is 0%. Shared-network intensity is therefore not inherently fraudulent and is not a supported explanation for ordinary-checkout friction.

## 10. Policy evidence and deterministic-rule context

Existing evidence/rule functions were applied descriptively to frozen feature rows only; no model score or decision was used or reconstructed.

| Population | Any evidence | At least 2 evidence codes | Any deterministic rule | Mean rule score |
|---|---:|---:|---:|---:|
| Development legitimate validation | 32.90% | 23.04% | 15.75% | 0.384 |
| PBRSS ordinary checkout | 31.20% | 18.86% | 15.67% | 0.253 |
| PBRSS charity | 11.73% | 11.73% | 71.27% | 0.919 |
| PBRSS B2B | 50.00% | 50.00% | 50.00% | 1.049 |

Ordinary checkout does not have elevated aggregate evidence/rule prevalence relative to development legitimate traffic. Charity's high shared-IP deterministic-rule prevalence coexists with 0% frozen REVIEW+, illustrating why these contextual signals must not be equated with decisions.

Policy v2 REVIEW at the model review threshold does **not** require block evidence. Evidence-code prevalence is therefore contextual diagnostic information, not a direct explanation for REVIEW decisions. Block evidence may withhold hard blocks, but without allowed score-to-row linkage this report does not attribute the low ordinary BLOCK rate to exact evidence states.

## 11. Calibration shift

**OBSERVED:** frozen PBRSS-v1 Brier is 0.156037 and ECE is 0.140679. In the frozen `[0.0, 0.1)` reliability bin, mean predicted risk is 0.0158 while the observed rate is 0.1454. In every higher frozen bin, predicted risk exceeds the observed rate—for example, 0.9245 predicted versus 0.8042 observed in `[0.9, 1.0]`.

This means the frozen sigmoid probability mapping transferred poorly to the shifted PBRSS distribution: it underestimates risk in the dominant low bin and overestimates it in higher bins. No recalibration was performed or proposed against consumed PBRSS-v1.

**NOT PROVEN:** calibration error alone does not explain why ordinary checkout reached 25.30% REVIEW+. The available reliability artifact is aggregate, not scenario-by-bin or device-attribution evidence.

## 12. Connection to frozen Phase 2.6 ablations

The prior ablations provide sensitivity context, not new PBRSS experiments:

- Removing the broader relationship/entity family reduced PR-AUC by 0.0233, reduced attack REVIEW+, and modestly worsened legitimate outcomes. Current card-distribution shift therefore matters as a supported multivariate hypothesis, not proof.
- Removing `customer_id_present` increased legitimate friction materially in development. The current 39.26% presence rate versus 79.06% is aligned with a plausible loss of legitimate context.
- Removing trust/continuity features had a modest adverse development effect. Current age and successful-history shifts align with that prior direction.
- Removing individual card-diversity/card-change ratios did not recreate the targeted legitimate failure. They must not be blamed individually.
- Temporal shape, session churn, and long-horizon groups were redundant in development ablations. Their current distribution shifts do not establish causal importance under PBRSS.

No new ablation, feature removal, fit, or score was run.

## 13. Most likely explanation

**SUPPORTED HYPOTHESIS:** the evidence supports the hypothesis that ordinary-checkout friction emerged under a broad covariate shift combining:

1. sharply younger and less established device/customer histories;
2. substantially less customer identity and successful-checkout continuity;
3. failures spread across more rows, higher failure ratios, and more retry-after-decline behavior despite no increase in mean raw failure count;
4. dense, mostly same-session repeat attempts;
5. shifted amount variation and card-history distributions; and
6. a frozen sigmoid calibration mapping that transferred poorly to the PBRSS distribution.

This combination is more defensible than a single-feature explanation. Charity differs through zero customer continuity but extreme shared-network activity and micro-payment context; B2B has strong identity presence and higher card/entity history. Their lower friction shows that the frozen system's behavior depends on interacting histories, not one universally adverse signal.

## 14. What is not supported

- Exact claims that feature X caused specific devices to be reviewed.
- A claim that ordinary checkout has higher mean raw failure counts or longer decline streaks than development legitimate traffic.
- A claim that shared IP or CGNAT-like traffic caused ordinary-checkout friction.
- A claim that missing customer identity alone caused the failure.
- A claim that card diversity alone caused the failure.
- A claim that calibration alone caused all REVIEW friction.
- A claim that deterministic rules or block-evidence codes directly explain REVIEW decisions.
- A claim that charity's 0% REVIEW+ proves general real-world robustness.
- A claim that PBRSS is production Razorpay performance, a fresh blind test, or proof of production generalization.

## 15. Product implication

High attack coverage plus low hard legitimate blocking does not compensate for 20.72% legitimate REVIEW+ in a payment flow. REVIEW locally suppresses order creation and returns a review state; it is not Razorpay manual review, 3DS, OTP, or issuer verification. At this friction level, one in five legitimate benchmark devices experiences suppression, concentrated at one in four ordinary-checkout devices. The frozen evidence therefore does not support production readiness.

## 16. Recommended future work — not implemented

Future research should use production-calibrated development data, broader independent real-merchant validation, more representative ordinary-checkout histories, explicit out-of-distribution calibration research, and threshold/economic optimization only within a **new** development cycle. Any future model iteration requires a new development process and a new untouched evaluation source.

The consumed PBRSS-v1 suite must not be used for tuning, recalibration, threshold selection, or Model v3.2 development. **NONE OF THIS FUTURE WORK WAS IMPLEMENTED AFTER PBRSS.**

## 17. Final diagnosis

**MIXED.** The main strength is 96.40% attack REVIEW+ with only 0.16% legitimate BLOCK. The main limitation is 20.72% legitimate REVIEW+, concentrated at 25.30% in shifted ordinary-checkout traffic. The post-evaluation evidence supports material covariate and calibration shift, while deliberately stopping short of forbidden per-device causal attribution.

> On the predeclared PBRSS-v1 stress suite, Model v3.1 retained 96.4% attack REVIEW+ and only 0.16% legitimate BLOCK, but legitimate REVIEW+ rose to 20.72%, concentrated in shifted ordinary-checkout traffic. Post-evaluation diagnosis found material covariate and calibration shift; the consumed suite was not used for retuning.
