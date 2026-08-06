#!/usr/bin/env bash
# Deprecated: superseded by ./scripts/dev-db.sh switch
#
# The old model swapped snapshot contents in and out of one fixed active
# database. Branches now own their databases outright, so "init" is just
# "point backend/.env at this branch's database".
set -euo pipefail

echo "dev-db-init.sh is deprecated — use ./scripts/dev-db.sh switch" >&2
exec "$(dirname "$0")/dev-db.sh" switch "$@"
