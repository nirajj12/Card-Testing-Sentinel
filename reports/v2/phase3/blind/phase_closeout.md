# Phase 3 final blind challenge closeout

- Status: `blind_completed_passed`
- Seed: `20260828`
- Frozen policy: `phase2c_002`
- Policies evaluated: `1`
- No retraining, refitting, retuning, regeneration, or candidate search

## Safety

| Population | Review-or-higher | Allowance | Blocks | Allowance | Pass |
|---|---:|---:|---:|---:|:---:|
| overall_legitimate | 2/1700 | 51 | 0 | 17 | yes |
| normal_standard | 0/1200 | 24 | 0 | 6 | yes |
| normal_bad_luck | 2/100 | 5 | 0 | 2 | yes |
| flash_standard | 0/300 | 15 | 0 | 9 | yes |
| flash_hard_retry | 0/100 | 10 | 0 | 5 | yes |

## Effectiveness

| Attacker group | Review-or-higher | Blocks | Never detected |
|---|---:|---:|---:|
| burst | 120/120 | 113/120 | 0 |
| evasive | 79/90 | 65/90 | 11 |
| patient | 72/90 | 55/90 | 18 |

## Integrity and runtime

- Dataset manifest: `c2c092a31e8a618456255dfa52ce1fed44392a71f2edfd704e35b77ec0247172`
- Online/batch maximum difference: `0.0`
- Requests scored: `5254`
- Replay seconds: `2.129927`
- Requests/second: `2466.75`
- Final manifest: `written after report`

Potentially preventable attempts are an **offline replay upper bound—not observed or causal fraud prevention**.
