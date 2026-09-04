# Evaluation Explained

Sentinel has two main evaluation views. Both are synthetic and both are kept
separate from the interactive demo.

`REVIEW+` means the device received either `REVIEW` or `BLOCK`.

## Held-out development validation

The held-out Dataset v4.1 validation split contains 3,500 devices: 630 attack
and 2,870 legitimate.

| Metric | Result |
|---|---:|
| Attack `REVIEW+` | 93.4921% |
| Attack `BLOCK` | 67.4603% |
| Legitimate `REVIEW+` | 3.1359% |
| Legitimate `BLOCK` | 0.1394% |
| PR-AUC | 0.916860 |
| ROC-AUC | 0.969254 |
| Brier score | 0.041004 |
| ECE | 0.021435 |
| Log loss | 0.158360 |
| Counterfactual ordering | 20/20 pairs |

These results show strong separation on the development distribution. They are
not production accuracy or a guarantee about live attacks.

## PBRSS-v1 shifted stress test

PBRSS-v1 deliberately changes the synthetic distribution. It contains 5,000
devices: 1,250 attack and 3,750 legitimate. The stack was frozen before this
benchmark was scored, and it was not tuned afterward.

| Metric | Result |
|---|---:|
| Attack `REVIEW+` | 96.40% |
| Attack `BLOCK` | 59.12% |
| Legitimate `REVIEW+` | 20.72% |
| Legitimate `BLOCK` | 0.16% |
| PR-AUC | 0.646976 |
| ROC-AUC | 0.726189 |
| Brier score | 0.156037 |
| ECE | 0.140679 |
| Log loss | 0.653809 |
| Conclusion | `MIXED` |

Attack intervention remained high and hard blocks on legitimate devices stayed
low. However, legitimate `REVIEW+` friction and probability calibration became
much worse. These weaknesses are why `production_ready=false` remains the
honest status.

PBRSS precision is conditional on its synthetic 25% attack prevalence. It is
not expected production precision.

## Important offline limitation

PBRSS feature generation replays each complete generated lifecycle independently
of policy intervention and then applies the frozen model and policy. First
intervention and detection timing are therefore more defensible than the path
after an intervention. Post-intervention trajectories are less faithful to a
deployment where `REVIEW` or `BLOCK` would suppress payment processing.

PBRSS-v1 is an offline detector benchmark, not a fully closed-loop production
simulation.

For frozen evidence, see the
[PBRSS-v1 report](../../reports/phase_3c_pbrss_v1_one_score_evaluation.md) and
[technical report index](../../reports/README.md).
