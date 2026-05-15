#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Test seam for proving drift detection without mutating the checked-in schema.
SCHEMA_PATH="${INTRIC_JS_SCHEMA_PATH:-$ROOT_DIR/frontend/packages/intric-js/src/types/schema.d.ts}"
TMP_DIR="$(mktemp -d)"

cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

OPENAPI_JSON="$TMP_DIR/openapi.json"
GENERATED_SCHEMA="$TMP_DIR/schema.d.ts"

(
  cd "$ROOT_DIR/backend"
  OPENAPI_JSON="$OPENAPI_JSON" uv run python - <<'PY'
import json
import os

from intric.server.main import app

with open(os.environ["OPENAPI_JSON"], "w", encoding="utf-8") as openapi_file:
    json.dump(app.openapi(), openapi_file)
PY
)

(
  cd "$ROOT_DIR/frontend/packages/intric-js"
  bun x openapi-typescript "$OPENAPI_JSON" \
    -o "$GENERATED_SCHEMA" \
    --default-non-nullable=false
  bun x prettier --write "$GENERATED_SCHEMA" --config .prettierrc >/dev/null
)

if ! diff -u "$SCHEMA_PATH" "$GENERATED_SCHEMA"; then
  cat >&2 <<'EOF'

Generated OpenAPI schema types are stale.

Regenerate from the current backend app.openapi() snapshot:

  cd backend
  OPENAPI_JSON=/tmp/eneo-openapi.json uv run python - <<'PY'
import json, os
from intric.server.main import app
with open(os.environ["OPENAPI_JSON"], "w", encoding="utf-8") as f:
    json.dump(app.openapi(), f)
PY
  cd ../frontend/packages/intric-js
  bun x openapi-typescript /tmp/eneo-openapi.json -o src/types/schema.d.ts --default-non-nullable=false
  bun x prettier --write src/types/schema.d.ts --config .prettierrc

EOF
  exit 1
fi

echo "Generated OpenAPI schema types are up to date."
