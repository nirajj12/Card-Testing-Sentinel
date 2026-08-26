# Phase 4 closeout

Final status: `phase4_completed`

## Scope and evidence boundary

Phase 4 provides a local FastAPI/Jinja2 application, a persistent SQLite live
state store, and a same-origin HTML/CSS/modular-vanilla-JavaScript operations
dashboard. No runtime dependency was added. No model training, calibration,
feature, threshold, policy, frozen dataset, blind decision, metric, ledger or
historical manifest was changed. No blind row was rescored.

The protected boundary passed read-only verification: 23 V1 release-manifest
entries, all 86 V1 dataset checks, all 27 V2 development checks, the Phase 2B
post-scoring final manifest, the Phase 2C correction/replacement/policy chain,
and the Phase 3 pre-access freeze, dataset manifest, final manifest and
post-scoring lifecycle. A second Phase 3 blind-scoring invocation remained
explicitly refused.

## Quality gates

- Phase 4: 30 passed, 0 failed, 0 skipped; decision-critical coverage 90%.
- Full repository: 280 passed, 0 failed, 0 skipped; whole-repository coverage
  80%. Two pre-existing environment warnings were reported and did not fail the
  suite.
- Ruff: all 174 eligible files formatted; lint passed.
- Security fixture gates: missing HMAC secret, tampered model, tampered policy,
  tampered manifest, missing artifact and wrong feature contract all failed
  closed. Strict contracts rejected client features, labels/scenario metadata,
  PAN, CVV and expiry.

The 80% whole-repository figure remains an honest historical limitation. No
frozen historical source was changed to increase it.

## Live runtime verification

The real application was started against an isolated temporary SQLite database
with a temporary test-only HMAC secret. Dashboard, liveness, readiness, system,
blind metrics, blind replay, runtime decisions and demo scenario endpoints all
returned HTTP 200. Precheck, outcome and checkout returned HTTP 200.

An identical precheck retry returned the same decision and state version,
reported itself as idempotent, did not create a second row, and is test-proven
not to invoke the model again. A conflicting retry returned HTTP 409. In a real
burst-style raw-event sequence, the frozen policy first blocked attempt 4, the
blocked outcome returned HTTP 409, and seven subsequent requests were still
independently scored. Restart recovery restored 12 decisions, 14 timeline
events and maximum state version 14 without rescoring persisted decisions.

SQLite reported WAL mode, a valid foreign key and `quick_check=ok`. Byte and
table inspection found no raw gateway card token, raw IP reference, PAN, CVV,
expiry or HMAC secret. Observed server logs contained only safe decision,
version and latency information. The temporary database is outside the release
manifest and the server was stopped after verification.

## Benchmark

The isolated real-routing benchmark recorded 300/300 successful measured
responses after 20 warmups, with no failed response omitted. Endpoint latency
was p50 1.262 ms, p95 1.448 ms, p99 1.662 ms and maximum 2.375 ms. Throughput
was 768.27 requests/second. Service-only latency was p50 0.264 ms, p95 0.309
ms, p99 0.333 ms and maximum 0.350 ms. The frozen artifacts loaded once;
per-request DataFrame construction count was zero. The benchmark used Python
3.11.15, FastAPI 0.115.0, Starlette 0.38.6 and httpx 0.27.2 with isolated
in-memory state; the live default is SQLite/WAL. These local-machine numbers
are evidence, not a production SLA.

## Browser verification

The running dashboard was inspected in the Codex in-app browser at 1440×1000,
768×900 and 390×844. Overview, Live Detection, Blind Replay and System all
rendered and navigated correctly. Live start, next, previous, play, pause and
reset worked; risk/decision badges, readable reason codes and causal timelines
were visible. Blind filters returned saved Phase 3 decisions and a readable
timeline. Loading and API-unavailable error states were observed.

There was no horizontal page overflow at 768 or 390 pixels. Keyboard focus had
a visible cyan indicator, decision meaning included text, all ten required
limitations were visible, and no raw token, IP or feature vector appeared. The
browser asset inventory contained only same-origin CSS, JavaScript and API
requests—no CDN, external font, image or remote asset.

One narrow Phase 4 UI issue was found and minimally fixed during browser QA:
live timeline cards had displayed state versions as attempt numbers. They now
display request ordinals. A loading-state panel and deterministic asset version
were also added so startup state is explicit and browser caches receive the
corrected renderer. The affected tests, Ruff and browser checks passed again.

## Integrity manifest and limitations

`artifacts/v2/phase4/phase4_hash_manifest.json` protects Phase 4 configuration,
source, template, static assets, scripts, tests, documentation, benchmark,
coverage, browser evidence, HTTP smoke evidence and this closeout. Its SHA-256
is recorded in `artifacts/v2/phase4/phase4_hash_manifest.sha256`; the mutable
runtime database, caches, logs, temporary browser files and secrets are
excluded.

This remains a synthetic single-process prototype with a global asynchronous
transition lock, local SQLite and no horizontal-scaling claim. Production needs
real merchant validation, authentication/authorization, rate limiting,
transactional distributed state, durable streams, distributed idempotency,
multiple workers, drift monitoring and human-review feedback. Risk score is
not a guaranteed fraud probability, early detection remains limited, and the
offline preventable-attempt count is an upper bound rather than observed fraud
prevention.
