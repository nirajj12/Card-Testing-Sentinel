# Phase 2B Modeling Design Proposal (NOT executed)

This document proposes a Phase 2B modeling and policy design. **Nothing in
this document has been run against training, validation, or blind data.** No
model has been trained, no candidate has been evaluated, no policy has been
selected, and no freeze has been created. The candidate *counts* below were
derived by calling the existing, frozen, unmodified
`card_testing_sentinel.v2.policy.selection.enumerate_policy_grid` function
against a new, unexecuted config file
(`configs/v2/phase2b/policy_grid_proposal.yaml`) -- pure combinatorics, not an
evaluation against any dataset.

## 1. Features

Keep the current 35 `MODEL_FEATURE_COLUMNS` unchanged as the baseline. Add, as
a *proposal* motivated by `phase2b_development_diagnosis.md` questions 7-8,
exactly four new feature candidates, all computable from request-known state
(no client-supplied thresholds/features):

1. `prior_attempts_14d` / `distinct_cards_14d` -- extend the existing 7-day
   window to 14 days, to test whether `attack_patient` (which is designed to
   stay under 7-day thresholds) becomes separable from `normal_bad_luck` at a
   longer horizon.
2. `amount_continuity_score_30d` -- a device's current amount's z-score
   against its own trailing 30-day amount distribution (not against a global
   distribution), to test the diagnosis's hypothesis that "probing" amount
   sequences differ from a shopper's own normal spend pattern even when
   absolute amounts are unremarkable.
3. `ip_rotation_ratio_24h` -- distinct IPs per device over 24h divided by
   distinct devices sharing each of those IPs (a rotation-intensity ratio,
   not a new client-supplied field -- computed entirely from already-recorded
   IP/device state), motivated by the shared-IP semantics already retained
   within a partition.
4. `checkout_completion_lag_seconds` -- time between an allowed/reviewed
   authorization and its recorded checkout completion, where available, as a
   behavioral-continuity signal distinct from `prior_successful_checkouts`.

Each is a *hypothesis*, not a requirement: whether any of them actually
improves worst-subtype coverage without breaking legitimate-population
budgets can only be established by training and evaluating on development
data, which is out of scope for this phase.

## 2. Model families

**No new model family is proposed.** Keep exactly `logistic_regression` and
`hist_gradient_boosting`, as before. The diagnosis (question 3) found the
frozen HGB candidate's *ranking* quality already strong (training-OOF PR-AUC
0.867, worst-subtype coverage 0.994); the demonstrated failure mode is
feature separability between legitimate slow/retry behavior and
patient/evasive attackers, and instability concentrated in one subtype across
folds -- neither is a model-capacity problem a third family would fix. Adding
a third family (e.g., gradient-boosted trees with monotonic constraints, or a
GNN/deep sequential model) is explicitly not justified by this evidence and
is excluded per the standing instruction against production infrastructure
without demonstrated need.

## 3. Device-grouped OOF and device weighting

Unchanged in structure from Phase 2: 5 folds, device-grouped (no device's
events split across folds), with device weighting balancing training mass
across `scenario_tag` so no single high-volume subtype (e.g.
`attack_burst`'s 5,183 training events from 480 devices) dominates the loss
relative to a low-volume subtype (e.g. `attack_evasive`'s 360 devices). Per
`grouped_oof_metrics_by_fold_and_scenario.csv`, fold-level instability was
found specifically in `attack_patient`; a Phase 2B run should report
per-fold, per-subtype metrics (not just the aggregate) as a first-class
output, not an afterthought, so instability like this is visible before a
candidate is selected rather than discovered post hoc.

## 4. Calibration candidates

Unchanged: `none`, `sigmoid`, `isotonic`, evaluated with the same
device-fraction holdout and minimum-positive-device threshold as Phase 2. The
diagnosis (question 4) found no leakage evidence and only a small-sample
disagreement in one reliability bin; there is no basis to change the
calibration method set itself. If the new features in section 1 are added,
calibration should be re-evaluated against the same objective
(`lowest_device_weighted_brier`, `lowest_expected_calibration_error`,
`lowest_log_loss`, `no_material_pr_auc_degradation`, `simpler_method`,
unchanged from `configs/v2/training.yaml`).

## 5. Separate review/block semantics

Adopt explicitly, as a first-class design decision rather than an artifact of
the grid: **review is the low-cost, high-recall action; block requires
corroborating evidence.** This is directly supported by the diagnosis
(question 9) -- every Phase 2 closest candidate failed on the *review*
budget before block was even a binding constraint, and the existing
`combined` family's AND-for-block / OR-for-review structure already encodes
this asymmetry. Phase 2B keeps that structure rather than inventing a new
one; if `phase2b_development_diagnosis.md`'s findings do not replicate once
new features are added (i.e., if the failure mode shifts to block rather
than review), this decision should be revisited rather than assumed.

## 6. Three policy families and an exactly-derived finite candidate grid

Keep the same three families (`rules_only`, `ml_only`, `combined`) and the
same enumeration function and ordering guarantees (unique, deterministic
`candidate_id`s; a strict grid with no partial acceptance). The proposed grid
(`configs/v2/phase2b/policy_grid_proposal.yaml`) searches more finely in
exactly the region where Phase 2's closest candidates sat (see that file's
header comment for the specific rationale per family) rather than
re-searching the whole space blindly.

**Exact planned candidate count: 78** (8 `rules_only` + 25 `ml_only` + 45
`combined`), computed by calling the real, frozen `enumerate_policy_grid`
against this proposal's config -- reproducible by any reviewer by running
that same call, since it touches no data.

## 7. Unchanged hard budgets

The five budget groups in `configs/v2/policy.yaml` (`overall_legitimate`,
`normal_standard`, `normal_bad_luck`, `flash_standard`, `flash_hard_retry`)
are proposed **unchanged**. Nothing in the development-only diagnosis
provides an independent business justification to loosen them -- the
diagnosis explains *why* Phase 2 candidates failed the existing budgets, it
does not argue the budgets themselves are wrong. Changing a budget is a
business decision outside this phase's scope.

## 8. Worst-subtype coverage as the primary objective

Unchanged from Phase 2's `selection_objective` ordering in
`configs/v2/policy.yaml`: worst-subtype review-or-higher coverage first,
then macro-subtype review coverage, then worst/macro block coverage, then
processing delay and legitimate-intervention minimization, then policy
simplicity. No change proposed; this ordering is what correctly surfaced
`attack_evasive`'s 4.44% worst-subtype coverage as the Phase 2 rules-only
failure mode, and should continue to do so for Phase 2B.

## 9. Deterministic tie-breaking

Unchanged: the existing `comparison_tuple` in `policy/selection.py` already
provides a fully deterministic total order (ending in
`policy_complexity` and a JSON-serialized candidate as a final tie-break),
which is reused as-is.

## 10. Fresh-validation generation protocol (NOT executed)

If Phase 2B training on development data produces at least one feasible
candidate under the unchanged budgets, a **new** validation population must
be generated -- never the existing (now-development) validation set, which is
disclosed and no longer blind. Proposed protocol, to be executed only in a
separately authorized phase:

1. Generate fresh devices under the same frozen Phase 1 generator/config
   (`configs/v2/generation.yaml`, `configs/v2/features.yaml`,
   `configs/v2/split.yaml`), using a new seed disjoint from the training seed
   (`20260825`) and the original validation generation, so device identities
   cannot overlap with either.
2. Verify structural denominators (population sizes, scenario proportions)
   match the frozen development population's proportions before any scoring
   occurs, exactly as `open_validation()` already checks (`5,422` /
   `2,000` device count assertions) for the existing set.
3. Write the fresh validation data to a new path under
   `data/v2/phase2b/fresh_validation/`, never overwriting
   `data/v2/development/`.
4. Build a Phase 2B freeze manifest (Gate F's `build_phase2b_freeze_manifest`)
   *before* any fresh-validation file is written, so the freeze verifiably
   predates first access -- mirroring the existing `training_freeze.json` /
   `first_validation_access.json` pattern.

## 11. One-time access guard

Reuse the existing pattern in `card_testing_sentinel.v2.evaluation.access`:
a `verify_training_freeze()`-equivalent gate that raises `PermissionError`
if the freeze is missing, tampered, or postdates the first access ledger
entry; and a `first_validation_access.json`-equivalent ledger written exactly
once, on first read, never overwritten. Gate F's `assert_absent_category`
already implements the fail-closed half of this (a fresh-validation or blind
artifact must not exist before it is authorized) and its tests prove it.

## 12. Failure behavior on zero feasible candidates

If Phase 2B's fresh validation run (whenever separately authorized) again
produces zero feasible candidates across all three families, the correct
behavior is the same one already demonstrated in Phase 2: **stop, report the
closest candidate per family with its exact excess counts, and do not weaken
a budget, relax a constraint, or partially accept a candidate merely to
report a result.** This phase's own instruction not to weaken a gate to
report success applies equally to any future Phase 2B outcome.

## 13. Policy-structure hypothesis: accept or reject?

The proposed hypothesis (high-confidence rules to block; calibrated ML to
review; uncertain blocks need combined evidence; separate thresholds;
patient/evasive detection needs causal cross-session/longer-window evidence)
is **accepted, on the evidence gathered in this phase**, specifically:

- Rules routing to block: **not yet supported** -- `rules_vs_ml_failure_analysis.csv`
  shows rules fire on so few devices (essentially never on evasive/patient,
  rarely on burst) that rules alone cannot be a block trigger for the
  subtypes that matter; rules remain best used as *corroborating* evidence
  for block, as the existing `combined` family already does, not as a
  standalone block trigger.
- ML routing to review: **supported** -- section 5 above.
- Uncertain blocks need combined evidence: **supported** -- section 5, and
  the existing `combined` family's AND-for-block structure already reflects
  it.
- Separate thresholds for review/block: **supported and already present**
  in the frozen config; no change needed structurally.
- Patient/evasive detection needs longer-window/cross-session evidence:
  **supported as a hypothesis, not yet validated** -- diagnosis question 8;
  this is precisely why section 1 proposes new features rather than assuming
  they will work.
