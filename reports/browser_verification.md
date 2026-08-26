# Installed Chromium verification

Run date: 2026-08-26. The completed frontend was opened in the installed Chromium-based in-app browser against the real local application and file-backed SQLite state. No frontend source or screenshot was redesigned during this hardening pass.

## Viewport matrix

| Viewport | Document width | Body width | Horizontal overflow | Result |
|---|---:|---:|---|---|
| 1440 × 1000 | 1440 | 1440 | None | Pass |
| 1024 × 900 | 1024 | 1024 | None | Pass |
| 768 × 900 | 768 | 768 | None | Pass |
| 390 × 844 | 390 | 390 | None | Pass |

At 390 px the interactive order was scenario controls → customer checkout → operations decision → persisted timeline. All elements remained within the viewport.

## Scenario matrix

| Scenario | Attempts | Browser-observed decisions | Result |
|---|---:|---|---|
| Normal customer | 2 | allow, allow | Pass |
| Normal bad luck | 4 | allow ×4 | Pass |
| Flash sale — standard | 3 | allow ×3 | Pass |
| Flash sale — hard retry | 5 | allow ×5 | Pass |
| Burst attacker | 8 | allow ×3, block ×5 | Pass |
| Evasive attacker | 9 | allow ×4, review ×2, block ×3 | Pass |
| Patient attacker | 9 | allow ×4, review ×2, block ×3 | Pass |

The burst first blocked at the API-selected attempt 4. Attempts 5–8 remained visible and were independently scored. Every scenario rendered all six allowlisted causal signals. Block rows used the exact lifecycle wording: “Authorization suppressed. Bank not contacted. No outcome event created.”

## Diagnostics

- Browser developer log: empty after all interactions.
- Broken assets: none; HTML, CSS, JavaScript modules, readiness, scenario and blind-summary requests loaded successfully.
- Unexpected HTTP 404, 409 or 422 responses: none during the browser run.
- Customer/operations separation: customer copy contained checkout status only; internal risk, evidence, state-version and policy data remained in operations.
- README screenshots: all four checked-in files have the required final viewport dimensions and match the unchanged final UI.

The browser tab was closed and the application process was stopped after verification.
