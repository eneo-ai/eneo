#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
BACKEND_DIR="$REPO_ROOT/backend"
FUTURE_BASELINE_FILE="$BACKEND_DIR/.type-check-future-baseline"
BASELINE_JSON="$BACKEND_DIR/.pyright-baseline.json"
STRICT_CONFIG="$BACKEND_DIR/pyrightconfig.strict.json"
RATCHET_SCRIPT="$BACKEND_DIR/scripts/pyright_ratcheting.py"

if [ -f "$FUTURE_BASELINE_FILE" ]; then
  # shellcheck disable=SC1090
  source "$FUTURE_BASELINE_FILE"
else
  FUTURE_BASELINE_COMMIT="$(git -C "$REPO_ROOT" rev-parse HEAD)"
fi

cd "$BACKEND_DIR"

normalize_paths() {
  sed '/^$/d' \
    | sed 's|^backend/||' \
    | sed -n '/^src\/intric\/.*\.py$/p' \
    | sort -u
}

FUTURE_CHANGED_FILES=$(
  git -C "$REPO_ROOT" diff --name-only --diff-filter=AMR \
    "$FUTURE_BASELINE_COMMIT"..HEAD -- "backend/src/intric" || true
)
WORKTREE_CHANGED_FILES=$(
  git -C "$REPO_ROOT" diff --name-only --diff-filter=AMR \
    -- "backend/src/intric" || true
)
STAGED_CHANGED_FILES=$(
  git -C "$REPO_ROOT" diff --name-only --diff-filter=AMR --cached \
    -- "backend/src/intric" || true
)
UNTRACKED_FILES=$(
  git -C "$REPO_ROOT" ls-files --others --exclude-standard \
    "backend/src/intric" || true
)

NEW_FILES_BASELINE=$(
  git -C "$REPO_ROOT" diff --name-only --diff-filter=A \
    "$FUTURE_BASELINE_COMMIT"..HEAD -- "backend/src/intric" || true
)
NEW_FILES_STAGED=$(
  git -C "$REPO_ROOT" diff --name-only --diff-filter=A --cached \
    -- "backend/src/intric" || true
)

ALL_FILES=$(
  printf "%s\n" \
    "$FUTURE_CHANGED_FILES" \
    "$WORKTREE_CHANGED_FILES" \
    "$STAGED_CHANGED_FILES" \
    "$UNTRACKED_FILES" \
    | normalize_paths
)
NEW_FILES=$(
  printf "%s\n" \
    "$UNTRACKED_FILES" \
    "$NEW_FILES_BASELINE" \
    "$NEW_FILES_STAGED" \
    | normalize_paths
)

if [ -z "$ALL_FILES" ]; then
  echo "No Python files to check."
  exit 0
fi

EXISTING_FILES=$(
  comm -23 \
    <(printf "%s\n" "$ALL_FILES") \
    <(printf "%s\n" "$NEW_FILES") \
    || true
)

if [ -n "$NEW_FILES" ]; then
  uv run pyright --project "$STRICT_CONFIG" $NEW_FILES
fi

if [ -n "$EXISTING_FILES" ]; then
  if [ ! -f "$BASELINE_JSON" ]; then
    echo "Missing $BASELINE_JSON. Generate it with:"
    echo "  cd backend"
    echo "  uv run pyright --outputjson | python scripts/pyright_ratcheting.py --write-baseline --current - --baseline .pyright-baseline.json"
    exit 1
  fi

  TMP_JSON="$(mktemp)"
  uv run pyright --outputjson $EXISTING_FILES > "$TMP_JSON" || true
  python "$RATCHET_SCRIPT" --baseline "$BASELINE_JSON" --current "$TMP_JSON"
fi
