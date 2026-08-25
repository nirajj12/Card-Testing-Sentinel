# V2 Phase 2 blocked at validation policy gate

The training freeze was created at `2026-08-25T13:59:19.992315+00:00` and validation was first opened at `2026-08-25T13:59:34.470123+00:00`.

All 32 candidates in the frozen grid were evaluated with intervention-aware raw lifecycle replay. Zero candidates met every overall and subgroup allowance, so no V2 policy was selected or frozen.

## Exact closest boundaries

- Rules-only `policy_007` exceeded only normal_bad_luck review-or-higher: 6/100 against an allowance of 5/100. Its worst-subtype attacker review coverage was 0.0444.
- ML-only `policy_023` was 33 device-count units over frozen subgroup allowances; see the machine-readable failures for exact review/block counts.
- Combined `policy_031` was 144 device-count units over frozen subgroup allowances.

The budgets, rules, feature list, model, calibration, policy forms, thresholds, grids, objective and metric definitions were not changed after validation access. The candidate table retains the exact comparison tuple and budget results for every candidate.
