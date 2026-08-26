# Phase 2B training-only closeout

No validation or blind population was generated or read, and no policy was evaluated.

- Selected model: `logistic_regression__02` (logistic_regression)
- Calibration: `isotonic`
- Model features: 44
- Serialization fixture: 128 rows; full OOF is recorded separately
- Online/batch parity: 21338 rows × 44 features, maximum difference 0.0
- Shuffled-label ROC-AUC: 0.495946
- Strongest single feature: `amount_continuity_history_available` F1=0.738165
- Exact unevaluated policy grid: 78 candidates
- Reproduction OOF maximum difference: 0.0
- Training freeze SHA-256: `4f6011774b7c4b43c08c401e94107aec8e8b3378b1a5ffd0b1a85cca2dea0ee8`

All performance values are training-only diagnostics, not held-out or production claims.
