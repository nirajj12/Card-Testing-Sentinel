# Dataset and feature methodology

The project uses deterministic synthetic development data. Each device belongs
to one of seven scenarios: normal standard, normal bad luck, flash standard,
flash hard retry, burst attack, evasive attack or patient attack.

Every authorization is represented by a request followed later by an outcome.
An approved request may later receive a checkout completion. Event timestamps
must include a timezone and ties are ordered with `event_sequence`.

Devices—not rows—are assigned to train or validation. Batch feature generation
replays each split independently using the same causal engine used online.
The ordered 44-feature allowlist excludes labels, population, subtype, scenario,
split, outcome, device/session identifiers and raw token fingerprints.

Feature families include request and processed velocity, card/BIN diversity,
cross-session behavior, decline streak and ratios, request timing, device and
session age, IP sharing and rotation, retry and amount continuity, campaign
context, and successful-checkout history. Missing history has explicit numeric
semantics rather than using future information.

Generated development CSVs are intentionally excluded from the submission.
They can be reproduced with `pipelines/generate_synthetic_data.py` and checked
with `pipelines/validate_dataset.py`.
