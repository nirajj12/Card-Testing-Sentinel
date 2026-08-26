# Model and policy evaluation

Development training uses deterministic device-grouped folds. Each device has
total evaluation weight one; training additionally balances legitimate and
attack device classes. Logistic regression and gradient-boosting candidates can
be compared on ranking and calibration metrics. The operational frozen artifact
contains the selected logistic model and fitted isotonic calibrator in one
immutable joblib file.

Sequential evaluation replays raw request/outcome/checkout events. The current
request is scored before its outcome. A block suppresses only the linked outcome
and checkout; later requests continue through the scorer. Device-level review
and block coverage are primary policy measurements.

## Frozen synthetic blind evidence

The saved result includes 1,700 legitimate and 300 attacker devices. Two
legitimate devices received review and none was blocked. Attacker
review-or-higher coverage was 271/300 and block coverage was 233/300:

| Attack behavior | Reviewed or blocked | Blocked | Never detected |
|---|---:|---:|---:|
| Burst | 120/120 | 113/120 | 0 |
| Evasive | 79/90 | 65/90 | 11 |
| Patient | 72/90 | 55/90 | 18 |

No attacker was detected within three attempts. Median first review was attempt
5 and median first block was attempt 7. Twenty-nine attackers were never
detected. The saved potentially-preventable count is an offline replay upper
bound, not observed or causal fraud prevention.

The application reads the exact saved metrics, device summary and event
decisions. It never regenerates or rescores blind rows.
