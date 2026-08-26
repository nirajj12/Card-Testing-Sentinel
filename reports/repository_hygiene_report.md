# Repository hygiene and sensitive-data audit

Run date: 2026-08-26. The complete pre-cleanup classification is in `reports/final_hardening_inventory.md`; cleanup occurred only after that inventory was written.

## Cleanup

Disposable Python, pytest and Ruff caches, coverage state, local logs, temporary browser state and generated runtime SQLite state were removed from the submission tree. Material cleanup was kept recoverable under a temporary-directory recovery folder for this session. Frozen runtime artifacts, blind evidence, policy, feature contract, release manifest, golden fixture, screenshots, tests, documentation and lock files were retained.

## Ignore coverage

`.gitignore` now covers environment secrets, HMAC secret files, SQLite databases plus WAL/SHM sidecars, logs, Python caches, Node modules, coverage outputs, browser/test residues and OS metadata.

## Sensitive-data findings

- Real `.env` or deployment secret files: **0**. `.env.example` contains placeholders only.
- Common high-entropy API-key/private-key signatures: **0**.
- Private local filesystem paths or usernames: **0**.
- Runtime databases, SQLite sidecars and logs in the repository: **0** after cleanup.
- PAN-like numeric matches: confined to hashes/metrics, the protected golden fixture, synthetic evidence, and a deliberate API rejection test; no usable PAN was found.
- CVV/expiry/token terms: documentation, safe UI disclosure, synthetic aliases and rejection tests only; the application does not collect those fields.
- IP literals: loopback, bind, private, or RFC documentation ranges only; no unexpected public IP literal was found.
- HMAC-secret references: environment-variable names, placeholders and explicitly labeled test-only values only.

The scan covered tracked and untracked text content while excluding Git internals, local dependency environments, Node modules, binary model bytes and the protected blind CSV bodies. No secret values are reproduced in this report.
