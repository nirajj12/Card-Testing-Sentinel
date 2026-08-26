# Architecture

Card-Testing Sentinel is a single-process FastAPI application with a causal
feature engine, immutable scorer and policy, repository interface, SQLite
implementation, and same-origin browser frontend.

An authorization request is validated and HMAC-protected before it reaches the
feature engine. Features are computed from previously committed state plus
request-known values. The frozen model produces a raw score; the fitted
isotonic layer maps it to the operational risk score. The policy then returns
allow, review or block. Only after that decision is request state committed.

Processor outcomes and checkout completions arrive as later transitions. They
cannot change a prior decision. Blocked requests reject linked outcomes and
checkouts, but later requests from the device remain independently scoreable.

One asynchronous transition lock preserves global ordering in the local
prototype. SQLite uses WAL, full synchronous writes, foreign keys, uniqueness
constraints and explicit transactions. Restart recovery replays sanitized
stored transitions, verifies decisions and state versions, and never rescans
saved blind evidence.

The runtime artifact registry verifies `artifacts/release_manifest.json`, loads
the scorer, policy and saved evaluation tables once, and fails readiness when a
required byte changes. Mutable SQLite state is not part of the manifest.
