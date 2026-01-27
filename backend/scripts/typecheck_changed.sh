#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
BACKEND_DIR="$REPO_ROOT/backend"
BASELINE_FILE="$BACKEND_DIR/.type-check-baseline"
FUTURE_BASELINE_FILE="$BACKEND_DIR/.type-check-future-baseline"

# shellcheck disable=SC1090
source "$BASELINE_FILE"

if [ -f "$FUTURE_BASELINE_FILE" ]; then
  # shellcheck disable=SC1090
  source "$FUTURE_BASELINE_FILE"
else
  FUTURE_BASELINE_COMMIT="$(git -C "$REPO_ROOT" rev-parse HEAD)"
fi

cd "$BACKEND_DIR"

AUDIT_FOCUS_FILES=(
  "src/intric/audit"
  "src/intric/api/audit/routes.py"
  "src/intric/files/file_router.py"
  "src/intric/files/file_service.py"
  "src/intric/users/user_router.py"
)

FUTURE_CHANGED_FILES=$(
  git -C "$REPO_ROOT" diff --name-only --diff-filter=AMR \
    "$FUTURE_BASELINE_COMMIT"..HEAD --relative=backend -- "backend/src/intric/**/*.py" || true
)
NEW_FILES=$(
  git -C "$REPO_ROOT" ls-files --others --exclude-standard \
    "backend/src/intric/**/*.py" | sed "s|^backend/||" || true
)

ALL_FILES=$(
  printf "%s\n" "${AUDIT_FOCUS_FILES[@]}" "$FUTURE_CHANGED_FILES" "$NEW_FILES" \
    | sed '/^$/d' \
    | grep -E '^src/intric(/|/.*\.py)$' \
    | sed 's|^backend/||' \
    | sort -u \
    || true
)

if [ -z "$ALL_FILES" ]; then
  echo "No audit or future Python files to check."
  exit 0
fi

uv run pyright $ALL_FILES
