#!/usr/bin/env bash
# Per-branch development databases.
#
# Every git branch owns a real Postgres database named eneo_<sanitized-branch>.
# A new branch's database is created once by cloning the database of the branch
# it was forked from; after that, switching branches only repoints
# backend/.env's POSTGRES_DB. Nothing is copied on a switch, so a branch's data
# is never overwritten and returning to a branch finds it exactly as it was
# left.
#
#   ./scripts/dev-db.sh switch      point backend/.env at this branch's database
#   ./scripts/dev-db.sh status      what the current branch is wired to
#   ./scripts/dev-db.sh prune       drop databases whose branch is gone
#   ./scripts/dev-db.sh fork <name> scratch copy of a branch database
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${REPO_ROOT}/backend/.env"
FALLBACK_BASE="develop"
DB_PREFIX="eneo_"

usage() {
  # Everything between the shebang and the first non-comment line.
  awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"
  cat <<'EOF'

Subcommands:
  switch [--base <branch>] [--no-migrate] [-y]
        Ensure this branch's database exists (cloning it from the base branch
        the first time), repoint backend/.env at it, and run alembic upgrade
        head. Prints the command to restart the backend.

  status
        Current branch, its database and size, the database backend/.env is
        actually pointing at, the recorded base branch, and the alembic
        revision compared to the repo's head.

  prune [--yes]
        List eneo_* databases with no matching local branch. Dry-run unless
        --yes is passed. Never touches the active database or eneo_develop.

  fork <name> [--from <branch>] [-y]
        Copy a branch's database to eneo_<name> without switching to it, for a
        scratch copy before something destructive.

Base branch resolution for a brand-new branch, first match wins:
  1. --base <branch>
  2. git config branch.<name>.eneoDbBase
  3. the branch recorded in the reflog as the one you forked from
  4. the nearest ancestor branch that already has a database
  5. develop
The resolved base is written to git config so it stays stable and can be
inspected or overridden later.
EOF
}

die() {
  echo "Error: $*" >&2
  exit 1
}

# --- container discovery ----------------------------------------------------
# Same label-based discovery the previous dev-db scripts used: find the compose
# project that owns a service named 'eneo', then its 'db' and 'eneo' containers.

discover_containers() {
  local project
  project="$(docker ps --filter label=com.docker.compose.service=eneo \
                       --format '{{.Label "com.docker.compose.project"}}' | head -1)"
  [ -n "$project" ] || die "no running compose project with an 'eneo' service. Is the devcontainer up?"

  DB_CONTAINER="$(docker ps --filter label=com.docker.compose.project="$project" \
                            --filter label=com.docker.compose.service=db \
                            --format '{{.Names}}' | head -1)"
  APP_CONTAINER="$(docker ps --filter label=com.docker.compose.project="$project" \
                             --filter label=com.docker.compose.service=eneo \
                             --format '{{.Names}}' | head -1)"
  [ -n "$DB_CONTAINER" ] && [ -n "$APP_CONTAINER" ] \
    || die "could not discover db/eneo containers in project '$project'."
}

# The docker socket is mounted into the devcontainer, so docker commands work
# from either side. Knowing which side we are on lets us skip a pointless
# `docker exec` into ourselves and print the right restart command.
IN_APP_CONTAINER=0
if [ -f /.dockerenv ] && [ "$REPO_ROOT" = "/workspace" ]; then
  IN_APP_CONTAINER=1
fi

psql_t1() {
  docker exec -i "$DB_CONTAINER" psql -U postgres -d template1 -v ON_ERROR_STOP=1 "$@"
}

psql_db() {
  local db="$1"; shift
  docker exec -i "$DB_CONTAINER" psql -U postgres -d "$db" -v ON_ERROR_STOP=1 "$@"
}

# One round trip per invocation instead of one per branch: the ancestor scan
# below asks "does this database exist?" for every local branch.
DB_LIST=""
load_db_list() {
  DB_LIST="$(psql_t1 -tAc "SELECT datname FROM pg_database")"
}

db_exists() {
  printf '%s\n' "$DB_LIST" | grep -qxF "$1"
}

db_size() {
  psql_t1 -tAc "SELECT pg_size_pretty(pg_database_size('$1'))" 2>/dev/null | tr -d ' '
}

kick_connections() {
  psql_t1 -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$1' AND pid <> pg_backend_pid();" >/dev/null
}

clone_db() {
  local dest="$1" src="$2"
  # CREATE DATABASE ... WITH TEMPLATE refuses to run while anything else is
  # connected to the template.
  kick_connections "$src"
  psql_t1 -c "CREATE DATABASE \"$dest\" WITH TEMPLATE \"$src\";" >/dev/null
  load_db_list
}

confirm() {
  local prompt="$1" ans=""
  [ "$ASSUME_YES" -eq 1 ] && return 0
  # No stdin (a hook, CI, a piped run that ran out of answers) reads as "no"
  # rather than killing the script under `set -e`.
  read -r -p "$prompt [y/N] " ans || { echo; return 1; }
  ans="$(printf '%s' "$ans" | tr 'A-Z' 'a-z')"
  [ "$ans" = "y" ] || [ "$ans" = "yes" ]
}

# --- names ------------------------------------------------------------------

# Unchanged from the original dev-db scripts so databases created by them keep
# working. Note it deletes '-' rather than mapping it, so feat/foo-bar and
# feat/foobar would collide; the length and emptiness checks below catch the
# sharper failures.
sanitize_branch() {
  printf '%s' "$1" | tr '/' '_' | tr 'A-Z' 'a-z' | tr -cd 'a-z0-9_'
}

db_name_for() {
  local name
  name="${DB_PREFIX}$(sanitize_branch "$1")"
  [ "$name" != "$DB_PREFIX" ] || die "branch '$1' sanitizes to an empty database name."
  [ "${#name}" -le 63 ] \
    || die "database name '$name' is ${#name} chars; Postgres identifiers stop at 63. Use a shorter branch name or --base."
  printf '%s' "$name"
}

current_branch() {
  local branch
  branch="$(git -C "$REPO_ROOT" symbolic-ref --short HEAD 2>/dev/null || true)"
  [ -n "$branch" ] || die "no symbolic branch (detached HEAD?). Check out a branch first."
  printf '%s' "$branch"
}

branch_exists() {
  git -C "$REPO_ROOT" rev-parse --verify --quiet "refs/heads/$1" >/dev/null 2>&1
}

# --- backend/.env -----------------------------------------------------------
# This script owns the read-modify-write of backend/.env. The file is denied to
# editing tools and shell redirects at it are blocked, so POSTGRES_DB is only
# ever changed here.

env_db_line_count() {
  grep -cE '^[[:space:]]*POSTGRES_DB=' "$ENV_FILE" || true
}

read_env_db() {
  [ -f "$ENV_FILE" ] || die "$ENV_FILE does not exist. Start the devcontainer once to create it."

  local count value
  count="$(env_db_line_count)"
  [ "$count" -ne 0 ] || die "no POSTGRES_DB= line in $ENV_FILE."
  [ "$count" -eq 1 ] || die "$count POSTGRES_DB= lines in $ENV_FILE; refusing to guess which one is live."

  value="$(grep -E '^[[:space:]]*POSTGRES_DB=' "$ENV_FILE" | head -1 | cut -d= -f2-)"
  value="${value%%#*}"                                  # inline comment
  value="$(printf '%s' "$value" | tr -d '[:space:]')"   # surrounding whitespace
  value="${value%\"}"; value="${value#\"}"              # double quotes
  value="${value%\'}"; value="${value#\'}"              # single quotes

  # The value is interpolated into SQL below, so it has to be a plain
  # identifier.
  printf '%s' "$value" | grep -qE '^[A-Za-z_][A-Za-z0-9_]*$' \
    || die "POSTGRES_DB in $ENV_FILE is '$value', which is not a plain identifier."
  printf '%s' "$value"
}

write_env_db() {
  local new="$1" tmp mode
  tmp="$(mktemp "${ENV_FILE}.dev-db.XXXXXX")"
  # Write beside the original and rename, so an interrupted run can never leave
  # a truncated .env behind.
  awk -v val="$new" '
    !done && /^[[:space:]]*POSTGRES_DB=/ { print "POSTGRES_DB=" val; done=1; next }
    { print }
  ' "$ENV_FILE" >"$tmp"
  mode="$(stat -f '%Lp' "$ENV_FILE" 2>/dev/null || stat -c '%a' "$ENV_FILE" 2>/dev/null || echo 600)"
  chmod "$mode" "$tmp"
  mv "$tmp" "$ENV_FILE"
}

# --- base branch resolution -------------------------------------------------

# resolve_base sets these rather than printing, so the rule that fired survives
# (a command substitution would resolve it in a subshell and lose it).
RESOLVED_BASE=""
BASE_RULE=""

# The start point the branch was actually created from, per the branch's own
# reflog ("branch: Created from develop"). This is the authoritative answer:
# `git switch -c new old` records `old` here, while the HEAD reflog only knows
# which branch you happened to be standing on.
#
# Resolves remote-tracking answers (origin/develop) to the local branch, and
# yields nothing for "Created from HEAD" so the caller can fall back.
branch_creation_source() {
  local branch="$1" msg candidate prefix="branch: Created from "
  msg="$(git -C "$REPO_ROOT" reflog show --format='%gs' "refs/heads/$branch" 2>/dev/null | tail -1)"
  case "$msg" in
    "$prefix"*) candidate="${msg#"$prefix"}" ;;
    *) return 0 ;;
  esac

  # "Created from HEAD" (plain `git switch -c new`) names no branch; the caller
  # falls back to the HEAD reflog, which is correct in exactly that case.
  if branch_exists "$candidate"; then
    printf '%s' "$candidate"
    return 0
  fi
  candidate="${candidate#*/}"   # origin/develop -> develop
  if branch_exists "$candidate"; then
    printf '%s' "$candidate"
  fi
  # Never fail: this runs inside a command substitution under `set -e`, where a
  # non-zero return would abort the whole script instead of falling through.
  return 0
}

# The branch you were on when this branch was created, per the HEAD reflog.
# Entries are newest-first, so the oldest "moving from X to <branch>" line is
# the creation event -- provided the branch is young enough to still be in the
# reflog at all. Only consulted when the branch reflog says "Created from HEAD",
# in which case the two agree by construction.
reflog_fork_source() {
  local branch="$1"
  git -C "$REPO_ROOT" log -g --format='%gs' HEAD 2>/dev/null | awk -v b="$branch" '
    {
      prefix = "checkout: moving from "
      if (index($0, prefix) == 1) {
        rest = substr($0, length(prefix) + 1)
        marker = " to " b
        if (length(rest) > length(marker) &&
            substr(rest, length(rest) - length(marker) + 1) == marker) {
          print substr(rest, 1, length(rest) - length(marker))
        }
      }
    }
  ' | tail -1
}

# Closest local branch that is behind HEAD and already has a database. Limiting
# the scan to branches with databases keeps it cheap and guarantees the clone
# source exists.
nearest_ancestor_with_db() {
  local branch="$1" best="" best_n="" b db n
  while read -r b; do
    [ "$b" = "$branch" ] && continue
    db="${DB_PREFIX}$(sanitize_branch "$b")"
    db_exists "$db" || continue
    git -C "$REPO_ROOT" merge-base --is-ancestor "$b" "$branch" 2>/dev/null || continue
    n="$(git -C "$REPO_ROOT" rev-list --count "$b..$branch" 2>/dev/null || echo "")"
    [ -n "$n" ] || continue
    if [ -z "$best_n" ] || [ "$n" -lt "$best_n" ]; then
      best="$b"
      best_n="$n"
    fi
  done < <(git -C "$REPO_ROOT" for-each-ref --format='%(refname:short)' refs/heads)
  printf '%s' "$best"
}

resolve_base() {
  local branch="$1" candidate

  candidate="$(git -C "$REPO_ROOT" config --get "branch.${branch}.eneoDbBase" 2>/dev/null || true)"
  if [ -n "$candidate" ] && branch_exists "$candidate"; then
    RESOLVED_BASE="$candidate"
    BASE_RULE="recorded in git config branch.${branch}.eneoDbBase"
    return
  fi

  candidate="$(branch_creation_source "$branch")"
  if [ -n "$candidate" ] && [ "$candidate" != "$branch" ] \
     && db_exists "${DB_PREFIX}$(sanitize_branch "$candidate")"; then
    RESOLVED_BASE="$candidate"
    BASE_RULE="this branch was created from it"
    return
  fi

  candidate="$(reflog_fork_source "$branch")"
  if [ -n "$candidate" ] && [ "$candidate" != "$branch" ] && branch_exists "$candidate" \
     && db_exists "${DB_PREFIX}$(sanitize_branch "$candidate")"; then
    RESOLVED_BASE="$candidate"
    BASE_RULE="reflog says you branched off it"
    return
  fi

  candidate="$(nearest_ancestor_with_db "$branch")"
  if [ -n "$candidate" ]; then
    RESOLVED_BASE="$candidate"
    BASE_RULE="nearest ancestor branch that has a database"
    return
  fi

  RESOLVED_BASE="$FALLBACK_BASE"
  BASE_RULE="fallback"
}

record_base() {
  git -C "$REPO_ROOT" config "branch.$1.eneoDbBase" "$2"
}

# --- alembic ----------------------------------------------------------------

run_alembic() {
  # Reads the .env we just rewrote, so no environment override is needed.
  if [ "$IN_APP_CONTAINER" -eq 1 ]; then
    ( cd "${REPO_ROOT}/backend" && PATH="${HOME}/.local/bin:${PATH}" uv run alembic "$@" )
  else
    docker exec -u vscode "$APP_CONTAINER" bash -i -c "cd /workspace/backend && uv run alembic $*"
  fi
}

print_restart_hint() {
  if [ "$IN_APP_CONTAINER" -eq 1 ]; then
    cat <<EOF

The Postgres connection was kicked. Restart the backend (and worker, if running):
  cd /workspace/backend && uv run start
EOF
  else
    cat <<EOF

The Postgres connection was kicked. Restart the backend (and worker, if running):
  docker exec -u vscode $APP_CONTAINER bash -i -c "cd /workspace/backend && uv run start"
EOF
  fi
}

# --- subcommands ------------------------------------------------------------

cmd_switch() {
  local branch db active base base_db source_db
  branch="$(current_branch)"
  db="$(db_name_for "$branch")"
  active="$(read_env_db)"
  load_db_list

  if db_exists "$db"; then
    if [ "$active" = "$db" ]; then
      echo "Branch '$branch' is already on database '$db' ($(db_size "$db"))."
    else
      echo "Branch '$branch' → existing database '$db' ($(db_size "$db"))."
    fi
  else
    if [ -n "$OPT_BASE" ]; then
      branch_exists "$OPT_BASE" || die "base branch '$OPT_BASE' does not exist locally."
      base="$OPT_BASE"
      BASE_RULE="--base"
    else
      resolve_base "$branch"
      base="$RESOLVED_BASE"
    fi
    base_db="$(db_name_for "$base")"
    source_db="$base_db"

    # First run: the active database predates this tooling and holds real work
    # for whatever branch you were last on. Cloning the base instead would
    # silently strand it. An explicit --base says you have already decided.
    if [ -z "$OPT_BASE" ] && [ "${active#"$DB_PREFIX"}" = "$active" ]; then
      echo "Active database '$active' is not a per-branch database."
      echo "Its contents belong to whichever branch you last worked on."
      if confirm "Seed '$db' from the active database '$active' instead of from base '$base_db'?"; then
        source_db="$active"
        BASE_RULE="seeded from the pre-existing active database"
      fi
    fi

    if [ "$source_db" = "$base_db" ]; then
      db_exists "$base_db" || die "base branch '$base' has no database ('$base_db'). Check it out and run 'switch' there first, or pass --base."
      echo "Branch '$branch' has no database yet."
      echo "  base:   $base ($BASE_RULE)"
      echo "  clone:  $base_db → $db"
      confirm "Create '$db' from '$base_db'?" || die "aborted."
    fi

    clone_db "$db" "$source_db"
    echo "Created '$db' from '$source_db'."
    [ "$source_db" = "$base_db" ] && record_base "$branch" "$base"
  fi

  if [ "$active" != "$db" ]; then
    write_env_db "$db"
    echo "backend/.env: POSTGRES_DB=$db (was $active)"
  fi

  if [ "$NO_MIGRATE" -eq 0 ]; then
    echo "Running alembic upgrade head..."
    run_alembic upgrade head
  fi

  print_restart_hint
}

cmd_status() {
  local branch db active base recorded rev head
  branch="$(current_branch)"
  db="$(db_name_for "$branch")"
  active="$(read_env_db)"
  load_db_list

  echo "branch:      $branch"
  if db_exists "$db"; then
    echo "database:    $db ($(db_size "$db"))"
  else
    echo "database:    $db (does not exist — run './scripts/dev-db.sh switch')"
  fi

  if [ "$active" = "$db" ]; then
    echo "backend/.env: POSTGRES_DB=$active"
  else
    echo "backend/.env: POSTGRES_DB=$active  ← does NOT match this branch"
  fi

  recorded="$(git -C "$REPO_ROOT" config --get "branch.${branch}.eneoDbBase" 2>/dev/null || true)"
  if [ -n "$recorded" ]; then
    echo "base:        $recorded (recorded)"
  else
    resolve_base "$branch"
    base="$RESOLVED_BASE"
    echo "base:        $base ($BASE_RULE, not yet recorded)"
  fi

  if db_exists "$active"; then
    rev="$(psql_db "$active" -tAc "SELECT version_num FROM alembic_version" 2>/dev/null | tr -d ' ' || true)"
    head="$(run_alembic heads 2>/dev/null | awk '{print $1}' | head -1 || true)"
    if [ -n "$rev" ] && [ -n "$head" ]; then
      if [ "$rev" = "$head" ]; then
        echo "alembic:     $rev (at head)"
      else
        # The database can legitimately sit ahead of the branch when it was
        # cloned from a branch carrying extra migrations, so state the
        # difference rather than prescribing a fix.
        echo "alembic:     $rev  (repo head: $head)"
      fi
    elif [ -n "$rev" ]; then
      echo "alembic:     $rev"
    fi
  fi
}

cmd_prune() {
  local active branch expected db orphans=() total=0 name
  active="$(read_env_db)"
  load_db_list

  expected="$(git -C "$REPO_ROOT" for-each-ref --format='%(refname:short)' refs/heads \
              | while read -r branch; do printf '%s%s\n' "$DB_PREFIX" "$(sanitize_branch "$branch")"; done)"

  while read -r name; do
    [ -n "$name" ] || continue
    case "$name" in
      "$DB_PREFIX"*) ;;
      *) continue ;;
    esac
    # Never drop the database in use, the shared baseline, or test databases.
    [ "$name" = "$active" ] && continue
    [ "$name" = "${DB_PREFIX}develop" ] && continue
    case "$name" in
      *_test) continue ;;
    esac
    printf '%s\n' "$expected" | grep -qxF "$name" && continue
    orphans+=("$name")
  done <<<"$DB_LIST"

  if [ "${#orphans[@]}" -eq 0 ]; then
    echo "No orphaned branch databases."
    return
  fi

  echo "Databases with no matching local branch:"
  for name in "${orphans[@]}"; do
    printf '  %-56s %s\n' "$name" "$(db_size "$name")"
  done
  total="${#orphans[@]}"

  if [ "$PRUNE_YES" -eq 0 ]; then
    echo
    echo "$total database(s) would be dropped. Re-run with --yes to drop them."
    return
  fi

  for name in "${orphans[@]}"; do
    kick_connections "$name"
    psql_t1 -c "DROP DATABASE \"$name\";" >/dev/null
    echo "Dropped $name"
  done
  load_db_list
}

cmd_fork() {
  local name dest src_branch src_db
  name="${1:-}"
  [ -n "$name" ] || die "fork needs a name: ./scripts/dev-db.sh fork <name>"

  src_branch="${OPT_FROM:-$(current_branch)}"
  src_db="$(db_name_for "$src_branch")"
  dest="$(db_name_for "$name")"
  load_db_list

  [ "$dest" != "$src_db" ] || die "fork target '$dest' is the source database itself."
  db_exists "$src_db" || die "source database '$src_db' does not exist."

  if db_exists "$dest"; then
    confirm "Database '$dest' already exists. Drop and recreate it?" || die "aborted."
    kick_connections "$dest"
    psql_t1 -c "DROP DATABASE \"$dest\";" >/dev/null
    load_db_list
  fi

  clone_db "$dest" "$src_db"
  echo "Forked '$src_db' → '$dest'."
  echo "It is a plain copy; nothing points at it until a branch named '$name' runs 'switch'."
}

# --- argument parsing -------------------------------------------------------

ASSUME_YES=0
NO_MIGRATE=0
PRUNE_YES=0
OPT_BASE=""
OPT_FROM=""
POSITIONAL=()

main() {
  local subcommand="${1:-}"
  [ $# -gt 0 ] && shift || true

  case "$subcommand" in
    ""|-h|--help|help)
      usage
      return 0
      ;;
  esac

  while [ $# -gt 0 ]; do
    case "$1" in
      -y|--yes)     ASSUME_YES=1; PRUNE_YES=1 ;;
      --no-migrate) NO_MIGRATE=1 ;;
      --base)       OPT_BASE="${2:-}"; [ -n "$OPT_BASE" ] || die "--base needs a branch name"; shift ;;
      --from)       OPT_FROM="${2:-}"; [ -n "$OPT_FROM" ] || die "--from needs a branch name"; shift ;;
      -h|--help)    usage; return 0 ;;
      -*)           die "unknown option '$1'. Run './scripts/dev-db.sh --help'." ;;
      *)            POSITIONAL+=("$1") ;;
    esac
    shift
  done

  case "$subcommand" in
    switch|status|prune|fork) ;;
    *) die "unknown subcommand '$subcommand'. Run './scripts/dev-db.sh --help'." ;;
  esac

  discover_containers

  case "$subcommand" in
    switch) cmd_switch ;;
    status) cmd_status ;;
    prune)  cmd_prune ;;
    fork)   cmd_fork "${POSITIONAL[@]+"${POSITIONAL[@]}"}" ;;
  esac
}

# Only dispatch when executed. Sourcing the script exposes the helpers on their
# own, which is how scripts/tests/test_dev_db.py exercises them without Docker.
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  main "$@"
fi
