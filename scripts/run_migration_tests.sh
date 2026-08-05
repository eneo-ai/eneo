#!/usr/bin/env bash
#
# Run the migration_isolation suite one file per pytest process.
#
# Each file in tests/integration/migrations/ drives the schema down and back
# up, and deliberately leaves the database at whatever revision the last test
# landed on. The Postgres testcontainer is session-scoped, so running the whole
# directory in one process makes every file inherit its predecessor's schema —
# a file that passes alone fails behind a sibling that downgraded past it.
#
# One process per file gives each its own container, which is the isolation the
# suite has always documented. Every file runs even after an earlier one fails,
# so a red run reports the full set rather than the first casualty.
#
# Usage: scripts/run_migration_tests.sh [extra pytest args...]

set -uo pipefail

cd "$(dirname "$0")/../backend" || exit 1

shopt -s nullglob
files=(tests/integration/migrations/test_*.py)
shopt -u nullglob

if [ ${#files[@]} -eq 0 ]; then
  echo "No migration test files found." >&2
  exit 1
fi

failed=()

for file in "${files[@]}"; do
  echo "::group::${file}"
  if ! uv run pytest -m migration_isolation "$file" "$@"; then
    failed+=("$file")
  fi
  echo "::endgroup::"
done

if [ ${#failed[@]} -gt 0 ]; then
  echo
  echo "Migration test files with failures (${#failed[@]}/${#files[@]}):" >&2
  for file in "${failed[@]}"; do
    echo "  - ${file}" >&2
  done
  exit 1
fi

echo
echo "All ${#files[@]} migration test files passed."
