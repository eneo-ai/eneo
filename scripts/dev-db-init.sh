#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${REPO_ROOT}/backend/.env"
BASELINE="eneo_develop"

PROJECT="$(docker ps --filter label=com.docker.compose.service=eneo \
                     --format '{{.Label "com.docker.compose.project"}}' | head -1)"
if [ -z "$PROJECT" ]; then
  echo "Error: no running compose project with an 'eneo' service. Is the devcontainer up?" >&2
  exit 1
fi
DB_CONTAINER="$(docker ps --filter label=com.docker.compose.project="$PROJECT" \
                          --filter label=com.docker.compose.service=db \
                          --format '{{.Names}}' | head -1)"
APP_CONTAINER="$(docker ps --filter label=com.docker.compose.project="$PROJECT" \
                           --filter label=com.docker.compose.service=eneo \
                           --format '{{.Names}}' | head -1)"
if [ -z "$DB_CONTAINER" ] || [ -z "$APP_CONTAINER" ]; then
  echo "Error: could not discover db/eneo containers in project '$PROJECT'." >&2
  exit 1
fi

# Detect whether we're running inside the eneo devcontainer (docker socket is
# mounted, so docker commands work either way; this lets us skip the wasteful
# `docker exec into self` for alembic and adjust the restart-instructions).
IN_APP_CONTAINER=0
if [ -f /.dockerenv ] && [ "$REPO_ROOT" = "/workspace" ]; then
  IN_APP_CONTAINER=1
fi

psql_t1() {
  docker exec -i "$DB_CONTAINER" psql -U postgres -d template1 -v ON_ERROR_STOP=1 "$@"
}

db_exists() {
  local n
  n="$(psql_t1 -tAc "SELECT 1 FROM pg_database WHERE datname='$1'")"
  [ "$n" = "1" ]
}

kick_connections() {
  psql_t1 -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$1' AND pid <> pg_backend_pid();" >/dev/null
}

confirm() {
  local prompt="$1" ans
  read -r -p "$prompt [y/N] " ans
  ans="$(printf '%s' "$ans" | tr 'A-Z' 'a-z')"
  [ "$ans" = "y" ] || [ "$ans" = "yes" ]
}

assume_yes=0
[ "${1:-}" = "-y" ] && assume_yes=1

branch="$(git -C "$REPO_ROOT" symbolic-ref --short HEAD 2>/dev/null || true)"
if [ -z "$branch" ]; then
  echo "Error: no symbolic branch (detached HEAD?). Check out a branch first." >&2
  exit 1
fi
sanitized="$(printf '%s' "$branch" | tr '/' '_' | tr 'A-Z' 'a-z' | tr -cd 'a-z0-9_')"
snapshot="eneo_${sanitized}"

active="$(grep -E '^POSTGRES_DB=' "$ENV_FILE" | head -1 | cut -d= -f2-)"
if [ -z "$active" ]; then
  echo "Error: could not read POSTGRES_DB from $ENV_FILE" >&2
  exit 1
fi

if [ "$active" = "$snapshot" ]; then
  echo "Error: active DB ($active) equals branch snapshot name ($snapshot)." >&2
  echo "This design keeps the active DB and snapshots distinct. Update backend/.env to use a fixed name (e.g. 'postgres')." >&2
  exit 1
fi

if ! db_exists "$BASELINE"; then
  echo "No '$BASELINE' baseline found."
  if [ $assume_yes -eq 0 ] && ! confirm "Snapshot current active DB ($active) as $BASELINE?"; then
    echo "Aborted."
    exit 1
  fi
  kick_connections "$active"
  psql_t1 -c "CREATE DATABASE $BASELINE WITH TEMPLATE $active;"
  echo "Bootstrapped $BASELINE from $active."
fi

if db_exists "$snapshot"; then
  source_db="$snapshot"
  echo "Branch '$branch' → restoring active DB from snapshot '$snapshot'."
else
  source_db="$BASELINE"
  echo "Branch '$branch' → no snapshot found; cloning active DB from '$BASELINE'."
fi

if [ $assume_yes -eq 0 ]; then
  echo
  echo "WARNING: this will REPLACE active DB '$active' with contents of '$source_db'."
  echo "Uncommitted changes will be lost. Run ./scripts/dev-db-commit.sh first to keep them."
  if ! confirm "Continue?"; then
    echo "Aborted."
    exit 1
  fi
fi

restore_suffix="$(date +%s)_$$"
restore_tmp="eneo_restore_tmp_${restore_suffix}"
restore_old="eneo_restore_old_${restore_suffix}"

if db_exists "$restore_tmp"; then
  echo "Removing leftover restore temp DB '$restore_tmp'."
  kick_connections "$restore_tmp"
  psql_t1 -c "DROP DATABASE $restore_tmp;"
fi

kick_connections "$source_db"
psql_t1 -c "CREATE DATABASE $restore_tmp WITH TEMPLATE $source_db;"

kick_connections "$active"
psql_t1 -c "ALTER DATABASE $active RENAME TO $restore_old;"
if ! psql_t1 -c "ALTER DATABASE $restore_tmp RENAME TO $active;"; then
  echo "Error: failed to rename '$restore_tmp' to '$active'. Restoring previous active DB." >&2
  psql_t1 -c "ALTER DATABASE $restore_old RENAME TO $active;" || true
  exit 1
fi

kick_connections "$restore_old"
psql_t1 -c "DROP DATABASE $restore_old;"
echo "Active DB '$active' replaced with contents of '$source_db'."

echo "Running alembic upgrade head..."
if [ $IN_APP_CONTAINER -eq 1 ]; then
  ( cd "${REPO_ROOT}/backend" && PATH="${HOME}/.local/bin:${PATH}" uv run alembic upgrade head )
else
  docker exec -u vscode "$APP_CONTAINER" bash -i -c "cd /workspace/backend && uv run alembic upgrade head"
fi

if [ $IN_APP_CONTAINER -eq 1 ]; then
  cat <<EOF

Done. Restart backend with:
  cd /workspace/backend && uv run start
EOF
else
  cat <<EOF

Done. Restart backend with:
  docker exec -u vscode $APP_CONTAINER bash -i -c "cd /workspace/backend && uv run start"
EOF
fi
