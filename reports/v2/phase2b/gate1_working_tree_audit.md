# Gate 1 — Working-Tree Change Audit (corrective pass)

Read-only commands used (no mutating git command was run at any point):
`git status --short`, `git diff --name-only HEAD`, `git diff --stat HEAD`,
`git diff HEAD -- <path>` (full diff review, every changed tracked file),
`git show HEAD:<path>` (used only for restoration, see below).

## Classification

**Category 1 — new Phase 2B work (6 new top-level directories, untracked):**
`artifacts/v2/phase2b/`, `configs/v2/phase2b/`, `reports/v2/phase2b/`,
`scripts/v2/phase2b/`, `src/card_testing_sentinel/v2/phase2b/`,
`tests/v2/phase2b/`.

**Category 2 — shared tooling change (1 file): `pyproject.toml`.** This is
**not** a Phase 2B-namespaced file and is reported honestly as a repo-wide
change: it adds a `[tool.ruff.format] exclude` list and two
`[tool.ruff.lint.per-file-ignores]` blocks. No other section of the file
changed (full diff reviewed).

**Category 3 — intentional current V2 source repair (12 files), each
diff-reviewed line-by-line and confirmed value-preserving:**
`scripts/v2/{analyze_training_data,freeze_policy,report_blocked_phase2,train_candidates}.py`
(trailing blank line removed only), the three empty `v2/*/__init__.py`
docstring files (same), `v2/evaluation/access.py` (hash-string dict
rewrapped with identical values + `datetime.timezone.utc` →
`datetime.UTC` alias), `v2/policy/blocked.py` and `v2/policy/evaluation.py`
(ruff-format line-wrap of long literals/f-strings, byte-identical text once
rejoined, plus one real, disclosed fix in `evaluation.py`: an unused
`training_freeze` local variable removed, F841 — the freeze verification
call itself still executes unchanged), `v2/evaluation/eda.py` (method-chain
reflow only), and `tests/v2/unit/test_phase2_contracts.py` (literal
reflow + the same `UTC` alias; no assertion changed).

**Category 4 — unauthorized V1 change: zero remaining.** Two V1 files
(`src/card_testing_sentinel/api/app.py`, `src/card_testing_sentinel/data/validation.py`)
were transiently modified earlier this session by an over-broad
`ruff check --fix` run. This was caught immediately by the routine
`docs/v1/release_manifest.sha256` check, and both files were restored to
their exact original bytes via `git show HEAD:<path>` (a read-only git
command — not checkout/reset/restore) before any further work. Both verify
against the V1 manifest now (see Protected-Hash Verification below).

**Category 5 — unauthorized historical Phase 2 change: zero remaining.**
Twelve source files hashed inside `training_freeze.json`'s
`phase2_frozen_artifact_hashes` (`v2/evaluation/{calibration,metrics,sequential}.py`,
`v2/modeling/{artifacts,candidates,features,folds,training,weights}.py`,
`v2/policy/{engine,rules,selection}.py`) were transiently reformatted
earlier this session. This was caught when `verify_training_freeze()`
raised `PermissionError` during a routine test run. All twelve were restored
to exact original bytes the same way (`git show HEAD:<path>`, read-only) and
now match `training_freeze.json`'s recorded hashes exactly (see below).

**Category 6 — local cache/temp, not project evidence:** `__pycache__/`
directories under the two new Phase 2B source/test packages; the diagnostic
venv at `$HOME/envs/card-testing-sentinel-v2b`; the failed Conda bootstrap at
`$HOME/miniforge3`; scratch coverage/proof directories under `/tmp`. None of
these are inside the git working tree.

Machine-readable classification:
`artifacts/v2/phase2b/engineering/working_tree_classification.json`.

## Restoration method (both incidents)

`git show HEAD:<path>` (read-only; prints the committed blob, does not touch
the working tree, index, or refs) piped to a normal file write, followed by
a SHA-256 comparison against the protected hash recorded in
`docs/v1/release_manifest.sha256` or `training_freeze.json`. No
`git checkout`, `reset`, `restore`, `clean`, or `stash` was used at any
point in this project.

## Protected-hash verification (this pass)

- V1 release manifest: **23/23 OK** (`shasum -a 256 -c docs/v1/release_manifest.sha256`).
- V2 Phase 1 protected inputs: **10/10 verified** via the real
  `verify_phase1_protected_inputs()` guard (not a re-implementation).
- V1 release entries via the real `verify_v1_release()` guard: **23/23 verified**.
- Historical Phase 2 training freeze: **verified** via the real
  `verify_training_freeze()` guard — all 23 frozen artifact/source hashes
  inside `training_freeze.json` match the current tree.
- Phase 2 closeout manifest: **6/6 OK**
  (`shasum -a 256 -c artifacts/v2/phase2_closeout_manifest.sha256`).

No unauthorized V1 or historical Phase 2 change remains in the working
tree. `razorpay (1).zip` is present, unmodified, and its hash matches the
V1 manifest entry exactly.
