# Python dependency security audit

Audit date: 2026-08-26. Source: `pip-audit` against the current Python Packaging Advisory Database, captured as machine-readable JSON before and after remediation.

## Result

- Before: **51 advisory records across 10 packages**. Those records represent 39 unique advisory identifiers; duplicated records came from the advisory database returning the same canonical issue through multiple aliases/sources.
- After, isolated patched environment: **0 known vulnerabilities**.
- No blanket ignores or vulnerability suppressions were used.
- Frozen model-critical packages stayed unchanged: scikit-learn 1.6.1, NumPy 1.26.4, SciPy 1.14.1 and Joblib 1.4.2.

## Complete classification

Every canonical advisory reported by the 51-record JSON result appears below. The “records” column accounts for duplicates so the table reconciles exactly to the original audit count.

| Package | Installed before | Advisory/CVE identifiers | Fixed version(s) published | Records | Direct/transitive | Runtime/development | Vulnerable code path used? | Recommended action | Final status |
|---|---:|---|---|---:|---|---|---|---|---|
| click | 8.1.7 | PYSEC-2026-2132 / CVE-2026-7246 | 8.3.3 | 1 | Transitive via Uvicorn | Runtime CLI dependency | Uvicorn uses Click for startup; the vulnerable `click.edit()` command-execution path is not called | Upgrade with Uvicorn stack | **Fixed at 8.4.2** |
| fonttools | 4.53.1 | CVE-2025-66034 | 4.60.2 | 1 | Transitive via Matplotlib | Development-only | No runtime font/designspace parsing; plotting pipeline only | Keep out of runtime and upgrade development lock | **Fixed at 4.63.0** |
| h11 | 0.14.0 | PYSEC-2026-348 / CVE-2025-43859 | 0.16.0 | 1 | Transitive via Uvicorn and HTTP core | Runtime | Yes, h11 parses inbound HTTP; the request-smuggling condition is web-facing | Upgrade immediately and retest HTTP lifecycle | **Fixed at 0.16.0** |
| idna | 3.8 | PYSEC-2026-215 / CVE-2026-45409 | 3.15 | 2 | Transitive via AnyIO/HTTPX | Runtime transitive and development client | Inbound API does not encode attacker-supplied domains; test HTTP clients can use it | Upgrade in both locks | **Fixed at 3.19** |
| Jinja2 | 3.1.4 | PYSEC-2026-1471 / CVE-2025-27516; PYSEC-2026-1472 / CVE-2024-56201; PYSEC-2026-1475 / CVE-2024-56326 | 3.1.5–3.1.6 | 3 | Direct | Runtime | Trusted repository templates are rendered; users cannot provide template source or filenames, so the exploit precondition was absent | Upgrade despite non-reachable untrusted-template path | **Fixed at 3.1.6** |
| Pillow | 10.4.0 | PYSEC-2026-165, 2249, 2250, 2252, 2253, 2254, 2255, 2256, 2257, 2874, 3451, 3453, 3454, 3493, 3494, 3495, 3496 | 12.1.1–12.3.0 | 24 | Transitive via Matplotlib | Development-only | The live application does not import Pillow or accept images/fonts; development plots use generated trusted inputs | Remove from runtime and upgrade development lock | **Fixed at 12.3.0** |
| pip | 25.1.1 | PYSEC-2026-1795 / CVE-2025-8869; 1796 / CVE-2026-1703; 196 / CVE-2026-8643; 2875 / CVE-2026-3219; 2876 / CVE-2026-6357; 3721 / CVE-2026-13346 | 25.3–26.2 | 7 | Environment packaging tool | Build/install only | Package installation and download paths are used during environment construction | Pin the installation toolchain before installing locks | **Fixed at 26.2.1** |
| pytest | 8.3.3 | PYSEC-2026-1845 / CVE-2025-71176 | 9.0.3 | 1 | Direct optional dependency | Development-only | Yes, pytest uses its Unix temporary-directory machinery during tests | Upgrade and run the complete suite | **Fixed at 9.1.1** |
| setuptools | 79.0.1 | PYSEC-2026-3447 / CVE-2026-59890 | 83.0.0 | 2 | Direct build-system requirement | Build/install only | Editable/wheel builds use setuptools; the vulnerable Unicode sdist-exclusion path is not used by runtime | Upgrade build-system pin and clean-install from scratch | **Fixed at 84.0.0** |
| Starlette | 0.38.6 | PYSEC-2026-161 / CVE-2026-48710; 1941 / CVE-2025-54121; 1943 / CVE-2024-47874; 2280 / CVE-2026-48817; 2281 / CVE-2026-48818; 248 / CVE-2026-54282; 249 / CVE-2026-54283 | 0.40.0–1.3.1 | 9 | Transitive via FastAPI | Runtime | Yes, routing, URL reconstruction, static files and HTTP handling are live. This application does not parse forms/multipart or subclass `HTTPEndpoint`, and the Windows UNC issue is not applicable on the verified POSIX host, but other URL/parser paths are web-facing | Upgrade FastAPI and Starlette together, then run full API/browser tests | **Fixed at 1.6.0** |

## Dependency separation

- `requirements-runtime.lock` contains the production FastAPI/Jinja/Uvicorn runtime, the exact frozen-model numerical stack, and Pandas for the retained lazy immutable-replay API.
- `requirements-dev.lock` adds HTTP clients, tests, linting, plotting and development data tooling.
- `requirements-lock.txt` remains the exact combined convenience lock.
- Docker installs only `requirements-runtime.lock`.

## Compatibility evidence

The patched candidate environment used CPython 3.11.13. It loaded the frozen Joblib with scikit-learn 1.6.1 and no `InconsistentVersionWarning`, passed release verification, retained the 44-feature contract, and passed the complete Python suite. Runtime compatibility still fails closed on critical-version mismatch.
