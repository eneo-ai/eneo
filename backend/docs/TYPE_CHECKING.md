# Type Checking (Pyright)

This repository uses Pyright to catch runtime issues like incorrect method names and service/repository mixups.

## Baseline Strategy

We use two baselines to balance audit slop detection and future changes:

- `backend/.type-check-baseline` tracks the audit slop baseline (Jan 15 commit).
- `backend/.type-check-future-baseline` tracks when we start enforcing new changes.
- Audit focus files are always checked.
- New or modified files after the future baseline are checked.

## Local Commands

### Audit slop sweep (Jan 15 audit commit)

```bash
cd backend
AUDIT_FILES=$(git -C .. diff --name-only a7f09f78^..a7f09f78 -- "backend/src/intric/**/*.py")
uv run pyright $AUDIT_FILES
```

### Audit focus + future changes

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

We keep `reportAttributeAccessIssue` and `reportCallIssue` as errors to catch wrong method names. `reportGeneralTypeIssues` is a warning to reduce legacy noise while audit slop is being addressed.

## Updating the Baseline

When type coverage improves, move the audit baseline forward:

```bash
cd backend
NEW_BASELINE=$(git rev-parse HEAD)
cat > .type-check-baseline <<EOF
# Type checking baseline for audit slop
BASELINE_COMMIT=$NEW_BASELINE
BASELINE_DATE=$(date +%Y-%m-%d)
EOF

## Updating the Future Baseline

After merging this branch, set the future baseline to the merge commit so only new work is enforced:

```bash
cd backend
NEW_BASELINE=$(git rev-parse HEAD)
cat > .type-check-future-baseline <<EOF
# Type checking baseline for future work
FUTURE_BASELINE_COMMIT=$NEW_BASELINE
FUTURE_BASELINE_DATE=$(date +%Y-%m-%d)
EOF
```
```
