#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT_DIR"

CONTAINER_NAME="${FLOW_PARITY_CONTAINER:-eneo-41ae93-eneo-1}"
RUN_BACKEND_TEST=0
VERBOSE=0
ALLOW_LOCAL=0

declare -a EXPECT_PATHS=(
  "backend/tests/unit/test_ai_builder_openapi_contract.py"
  "frontend/packages/intric-js/src/endpoints/flows.js"
  "frontend/packages/intric-js/src/intric.js"
  "frontend/apps/docs-site/src/content/docs/flows.mdx"
  "frontend/apps/docs-site/src/content/guides/flows-api-guide.mdx"
  "frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderDriver.ts"
  "frontend/apps/web/src/lib/features/flows/ai-builder/protocol.ts"
)
declare -a EXPECT_PATTERNS=(
  "backend/tests/unit/test_ai_builder_openapi_contract.py::/api/v1/flows/ai-builder/sessions"
  "frontend/packages/intric-js/src/intric.js::flows: initFlows(client)"
  "frontend/apps/docs-site/src/content/docs/flows.mdx::### AI Builder"
  "frontend/apps/docs-site/src/content/guides/flows-api-guide.mdx::#### AI Builder"
  "frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderDriver.ts::/api/v1/flows/ai-builder/sessions"
  "frontend/apps/web/src/lib/features/flows/ai-builder/protocol.ts::requirements_summary"
)
declare -a REJECT_PATTERNS=()

action_usage() {
  cat <<'USAGE'
Usage:
  scripts/check-flow-ai-builder-parity.sh [options]

Options:
  --backend-openapi-test       Run backend/tests/unit/test_ai_builder_openapi_contract.py
  --expect-path <path>         Add another required file path
  --expect-pattern <spec>      Require FILE::PATTERN to match (repeatable)
  --reject-pattern <spec>      Require FILE::PATTERN to be absent (repeatable)
  --container <name>           Override docker container name (default: eneo-41ae93-eneo-1)
  --allow-local                Allow host pytest fallback when container is unavailable
  --verbose                    Print successful checks too
  -h, --help                   Show help

Examples:
  scripts/check-flow-ai-builder-parity.sh --backend-openapi-test
  scripts/check-flow-ai-builder-parity.sh \
    --expect-pattern 'frontend/packages/intric-js/src/endpoints/flows.js::aiBuilder' \
    --expect-pattern 'frontend/apps/docs-site/src/content/guides/flows-api-guide.mdx::AI Builder'
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --backend-openapi-test)
      RUN_BACKEND_TEST=1
      shift
      ;;
    --expect-path)
      EXPECT_PATHS+=("$2")
      shift 2
      ;;
    --expect-pattern)
      EXPECT_PATTERNS+=("$2")
      shift 2
      ;;
    --reject-pattern)
      REJECT_PATTERNS+=("$2")
      shift 2
      ;;
    --container)
      CONTAINER_NAME="$2"
      shift 2
      ;;
    --allow-local)
      ALLOW_LOCAL=1
      shift
      ;;
    --verbose)
      VERBOSE=1
      shift
      ;;
    -h|--help)
      action_usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      action_usage >&2
      exit 2
      ;;
  esac
done

failures=0

for path in "${EXPECT_PATHS[@]-}"; do
  if [[ ! -e "$path" ]]; then
    echo "[missing] $path" >&2
    failures=$((failures + 1))
  elif [[ "$VERBOSE" -eq 1 ]]; then
    echo "[ok] $path"
  fi
done

if [[ "${#EXPECT_PATTERNS[@]}" -gt 0 ]]; then
  for spec in "${EXPECT_PATTERNS[@]}"; do
    file="${spec%%::*}"
    pattern="${spec#*::}"
    if [[ "$file" == "$pattern" ]]; then
      echo "[invalid-pattern-spec] $spec (expected FILE::PATTERN)" >&2
      failures=$((failures + 1))
      continue
    fi
    if [[ ! -f "$file" ]]; then
      echo "[missing-for-pattern] $file" >&2
      failures=$((failures + 1))
      continue
    fi
    if ! rg -n --fixed-strings "$pattern" "$file" >/dev/null 2>&1; then
      echo "[pattern-missing] $file :: $pattern" >&2
      failures=$((failures + 1))
    elif [[ "$VERBOSE" -eq 1 ]]; then
      echo "[ok-pattern] $file :: $pattern"
    fi
  done
fi

if [[ "${#REJECT_PATTERNS[@]}" -gt 0 ]]; then
  for spec in "${REJECT_PATTERNS[@]}"; do
    file="${spec%%::*}"
    pattern="${spec#*::}"
    if [[ "$file" == "$pattern" ]]; then
      echo "[invalid-reject-pattern-spec] $spec (expected FILE::PATTERN)" >&2
      failures=$((failures + 1))
      continue
    fi
    if [[ ! -f "$file" ]]; then
      echo "[missing-for-reject-pattern] $file" >&2
      failures=$((failures + 1))
      continue
    fi
    if rg -n --fixed-strings "$pattern" "$file" >/dev/null 2>&1; then
      echo "[reject-pattern-hit] $file :: $pattern" >&2
      failures=$((failures + 1))
    elif [[ "$VERBOSE" -eq 1 ]]; then
      echo "[ok-reject-pattern] $file :: $pattern"
    fi
  done
fi

if [[ "$RUN_BACKEND_TEST" -eq 1 ]]; then
  if docker ps --format '{{.Names}}' | rg -x "$CONTAINER_NAME" >/dev/null 2>&1; then
    echo "[run] docker exec $CONTAINER_NAME /workspace/.venv/bin/pytest backend/tests/unit/test_ai_builder_openapi_contract.py"
    docker exec "$CONTAINER_NAME" sh -lc 'cd /workspace && /workspace/.venv/bin/pytest backend/tests/unit/test_ai_builder_openapi_contract.py'
  elif [[ "$ALLOW_LOCAL" -eq 1 ]]; then
    echo "[run-local-fallback] pytest backend/tests/unit/test_ai_builder_openapi_contract.py"
    pytest backend/tests/unit/test_ai_builder_openapi_contract.py
  else
    echo "[container-missing] requested backend OpenAPI test but container '$CONTAINER_NAME' is unavailable; rerun with --allow-local to permit host fallback" >&2
    exit 1
  fi
fi

if [[ "$failures" -gt 0 ]]; then
  echo "Parity check failed with $failures issue(s)." >&2
  exit 1
fi

echo "Flow/AI Builder parity check passed."
