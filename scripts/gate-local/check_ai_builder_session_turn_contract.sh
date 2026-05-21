#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
if [[ $# -gt 0 ]]; then
    SCAN_ROOTS=("$1")
else
    SCAN_ROOTS=(
        "${REPO_ROOT}/backend/src/intric/flows/ai_builder"
        "${REPO_ROOT}/backend/tests/integration/flows"
        "${REPO_ROOT}/backend/tests/unittests/flows/ai_builder"
    )
fi

for scan_root in "${SCAN_ROOTS[@]}"; do
    if [[ ! -d "$scan_root" ]]; then
        echo "check_ai_builder_session_turn_contract: missing scan root: $scan_root" >&2
        exit 1
    fi
done

loose_hits=$(grep -R --include='*.py' -nE '\blease_request_id\b|\blease_lock_token\b' "${SCAN_ROOTS[@]}" 2>/dev/null || true)
if [[ -n "$loose_hits" ]]; then
    echo "SESSION-TURN FAIL: loose active-turn lease primitives found." >&2
    echo "$loose_hits" >&2
    exit 1
fi

optional_hits=$(
    grep -R --include='*.py' -nE 'SessionSend(Lease|Turn)[[:space:]]*\|[[:space:]]*None|Optional\[[[:space:]]*SessionSend(Lease|Turn)[[:space:]]*\]' "${SCAN_ROOTS[@]}" 2>/dev/null \
        | grep -vE '/ai_builder_repo\.py:[0-9]+:[[:space:]]*lease: SessionSendLease \| None,' \
        || true
)
if [[ -n "$optional_hits" ]]; then
    echo "SESSION-TURN FAIL: active SessionSendLease/SessionSendTurn cannot be optional." >&2
    echo "$optional_hits" >&2
    exit 1
fi

turn_module="${REPO_ROOT}/backend/src/intric/flows/ai_builder/ai_builder_session_turn.py"
if [[ -f "$turn_module" ]]; then
    import_hits=$(
        grep -nE '^(from|import) ' "$turn_module" \
            | grep -vE '^([0-9]+:from __future__ import annotations|[0-9]+:from dataclasses import dataclass|[0-9]+:from uuid import UUID)$' \
            || true
    )
    if [[ -n "$import_hits" ]]; then
        echo "SESSION-TURN FAIL: ai_builder_session_turn.py must stay a leaf module." >&2
        echo "$import_hits" >&2
        exit 1
    fi
fi

echo "check_ai_builder_session_turn_contract: clean"
