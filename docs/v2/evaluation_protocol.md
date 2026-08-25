# V2 evaluation protocol

## Roadmap

- **Phase 1 (current):** preserve/audit V1; generate train/validation development lifecycle data; define privacy and causal contracts; implement one state engine plus batch replay; validate leakage, overlap, shortcuts, determinism, and parity.
- **Phase 2 (not authorized):** training-only EDA, evidence-based feature pruning, grouped CV, Logistic Regression/HGB and at most one justified candidate, calibration, validation-only policy selection, and freezing.
- **Phase 3 (not authorized):** after freeze, accept a new `V2_BLIND_TEST_SEED` or evaluator bundle and evaluate once without retuning.
- **Phase 4 (not authorized):** stateful API, replay UI, demo packaging, and proportionate deployment hardening.

The V1 test is the legacy seen V1 benchmark and is excluded from every V2 generator, feature, candidate, calibration, threshold, or policy decision.

## Development boundary

Only device-disjoint train and validation assignments exist. Generator calibration, shortcut analysis, and sanity classifiers use train only. Validation is limited in Phase 1 to structural counts, domains, parity, and overlap. Development sanity scores are data-quality diagnostics, never model-performance claims.

Development evaluation is **isolated group evaluation**, not chronological
online or transductive evaluation. Raw data retains realistic IP fingerprints
shared across partitions, but feature replay creates a fresh state engine per
split. Events remain globally ordered by `(timestamp, event_sequence)` inside
each split, so shared-IP concurrency is preserved among devices belonging to
that split while train state can never enter validation rows and validation
state can never enter train rows. A later production replay may be globally
chronological, but that is a different reporting protocol and cannot be used
for Phase 2 model selection.

## Future Phase 2 selection

Reject candidates exceeding any overall or legitimate-subgroup review/block budget. Among feasible candidates maximize worst-subtype attacker review-or-higher coverage, then macro-average subtype coverage, then block coverage, then minimize delay/cost. Deterministic ties prefer fewer legitimate interventions and the simpler policy. Compare rules-only, calibrated ML-only, and one interpretable hybrid; ML need not win. Review and block remain distinct unless a deliberate two-action policy is documented.

Primary reports use device-sequential numerators/denominators, all-attacker detection-within-K denominators, never-detected subtype counts, subgroup false review/block rates, exact pre-authorization request/processed/card terminology, and Wilson intervals. Row metrics and calibration (Brier plus ECE/curve) are secondary. Cost indices declare assumptions; no currency-savings claim is allowed. Potentially preventable counts remain noncausal offline upper bounds.

## Blind challenge and ledger

Phase 2 freezes generator version, development hashes, features, model, calibration, policy, guardrails, metrics, and plots before a seed/bundle exists. The later challenge uses new opaque IDs, a later period, and declared parameter perturbations. The Phase 3 command writes a content-addressed ledger entry containing pre-access Git commit when available, protected hashes, challenge hash, command, UTC timestamp, and output hashes. Existing ledger/final outputs make the standard evaluator refuse. A repository owner can bypass a local guard; the ledger makes the official run auditable rather than mathematically impossible. Nothing is retuned afterward.
