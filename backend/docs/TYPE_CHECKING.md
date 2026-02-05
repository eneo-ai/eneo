# Type Checking (Pyright)

This repository uses Pyright to catch runtime issues like incorrect method names and service/repository mixups.

## Baseline Strategy

We use baselines to avoid legacy noise while blocking regressions:

- `backend/.pyright-baseline.json` captures existing Pyright errors at a point in time and is committed to the repo.
- `backend/.type-check-future-baseline` defines which tracked files count as new or modified in CI.
- New files are checked in strict mode.
- Existing modified files are checked in basic mode, but only new diagnostics fail (ratcheting).
- Ratcheting compares error-level diagnostics by default (warnings are not gated).
- Local runs include staged, unstaged, and untracked files.

## What It Checks

- Scope: `backend/src/intric/**/*.py` only.
- New files: strict Pyright via `backend/pyrightconfig.strict.json`.
- Modified existing files: base Pyright via `backend/pyrightconfig.json`, but only new diagnostics fail.
- CI: uses `.type-check-future-baseline` to decide which tracked files are new/modified on the branch.

## What It Does Not Check

- Unchanged legacy files (no noise from pre-existing issues).
- Tests and migrations (excluded by config).
- Warning-level diagnostics (ratchet only gates errors).
- Frontend or non-`src/intric` Python code.
- Line-level diffs (ratcheting is file-level, not per-line).

## Local Commands

### Audit sweep (optional, Jan 15 audit commit)

```bash
cd backend
AUDIT_FILES=$(git -C .. diff --name-only a7f09f78^..a7f09f78 -- "backend/src/intric/**/*.py")
uv run pyright $AUDIT_FILES
```

### Changed files (strict new + ratchet)

```bash
cd backend
./scripts/typecheck_changed.sh
```

### Single file

```bash
cd backend
uv run pyright src/intric/files/file_router.py
```

## Editor Support

Install the VS Code Pylance extension. It uses the same engine as Pyright and reads `pyrightconfig.json` automatically.

## Configuration Notes

We keep `reportAttributeAccessIssue` and `reportCallIssue` as errors to catch wrong method names. Base config keeps `reportGeneralTypeIssues` as a warning to reduce legacy noise, while strict config raises it to an error for new files.

If you want to gate warnings as well, run ratcheting with `--include-warnings` or add it to `backend/scripts/typecheck_changed.sh`. If you enable warning gating, regenerate the baseline with `--include-warnings` too.

## Ratcheting Options

By default, ratcheting compares file + rule + message + line/column ranges. This is stricter and can flag errors as "new" when large refactors move code around.

If you are doing a big refactor and want to ignore line/column movement, set `RATCHET_IGNORE_RANGE=1` (or pass `--ignore-range` to `scripts/pyright_ratcheting.py`). This compares only file + rule + message + severity.

## Updating the Baselines

Refresh the Pyright diagnostic baseline when type coverage improves or you intentionally accept existing errors:

```bash
cd backend
uv run pyright --outputjson | python scripts/pyright_ratcheting.py \
  --write-baseline --current - --baseline .pyright-baseline.json
```

To include warnings in the baseline, add `--include-warnings` to the command above.

Move the future baseline forward so only new work is enforced:

```bash
cd backend
NEW_BASELINE=$(git rev-parse HEAD)
cat > .type-check-future-baseline <<EOF
# Type checking baseline for future work
FUTURE_BASELINE_COMMIT=$NEW_BASELINE
FUTURE_BASELINE_DATE=$(date +%Y-%m-%d)
EOF
```
