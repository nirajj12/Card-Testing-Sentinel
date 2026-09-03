# Architecture

Card-Testing Sentinel is a single-process FastAPI application with a causal
feature engine, immutable scorer and policy, repository interface, SQLite
implementation, and same-origin browser frontend.

An authorization request is validated and HMAC-protected before it reaches the
feature engine. Features are computed from previously committed state plus
request-known values. The active frozen Model v3.1 Histogram Gradient Boosting
classifier produces a raw score; sigmoid calibration maps it to the operational
risk score. The retained Policy v2 then returns allow, review or block. Only
after that decision is request state committed.

In the production-shaped Razorpay flow, payment outcomes and checkout
completions arrive only through verified, correlated gateway events. The normal
live API exposes no direct outcome or checkout-history write route. These later
transitions cannot change a prior decision; they affect future prechecks only.
Blocked requests reject linked outcomes and checkouts, but later requests from
the device remain independently scoreable.

The explicitly labeled demo API uses server-generated lifecycle transitions
for a dedicated demo merchant and per-run namespaced identities. It exercises
the same scoring machinery without accepting arbitrary browser-submitted
gateway outcomes for live checkout identifiers.

One asynchronous transition lock preserves global ordering in the local
prototype. SQLite uses WAL, full synchronous writes, foreign keys, uniqueness
constraints and explicit transactions. Restart recovery replays sanitized
stored transitions, verifies decisions and state versions, and never rescans
saved blind evidence.

The runtime artifact registry verifies `artifacts/release_manifest.json`, loads
the scorer, policy and saved evaluation tables once, and fails readiness when a
required byte changes. Mutable SQLite state is not part of the manifest.

Policy v2 was selected historically with Model v2 and intentionally retained
unchanged when Model v3.1 became active. `configs/runtime_v3_1.yaml` is the
authoritative current binding. Model v2 and isotonic calibration remain only in
frozen historical evidence.
