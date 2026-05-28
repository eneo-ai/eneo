#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DB_CONTAINER="eneo_devcontainer-db-1"
ENV_FILE="${REPO_ROOT}/backend/.env"

psql_t1() {
  docker exec -i "$DB_CONTAINER" psql -U postgres -d template1 -v ON_ERROR_STOP=1 "$@"
}

kick_connections() {
  psql_t1 -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$1' AND pid <> pg_backend_pid();" >/dev/null
}

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

echo "Snapshotting active DB '$active' → '$snapshot' (branch: $branch)..."
kick_connections "$active"
psql_t1 -c "DROP DATABASE IF EXISTS $snapshot;"
psql_t1 -c "CREATE DATABASE $snapshot WITH TEMPLATE $active;"
echo "Snapshot '$snapshot' saved. Backend connection was kicked — restart if needed."
