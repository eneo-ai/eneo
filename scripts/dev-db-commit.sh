#!/usr/bin/env bash
# Deprecated: there is nothing left to commit.
#
# This used to copy the shared active database into a per-branch snapshot so
# switching away would not lose it. Branches now own their databases directly,
# so the work is already persisted the moment it is written — switching away
# and back is lossless with no save step.
set -euo pipefail

cat >&2 <<'EOF'
dev-db-commit.sh is deprecated and did nothing.

Your branch's data lives in its own database and is never overwritten by a
switch, so there is no snapshot to take. Switching away and back is lossless.

  ./scripts/dev-db.sh status         where this branch's data lives
  ./scripts/dev-db.sh fork <name>    scratch copy before something destructive
EOF
