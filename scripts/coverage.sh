#!/usr/bin/env bash
#
# Whole-system coverage: where is the code untested?
#
# Runs the frontend (host) and backend (devcontainer) test suites with coverage,
# then prints the least-covered files per side and points at the clickable HTML
# reports (red lines = untested). Run it now and then to spot gaps — "did we miss
# testing an important function?".
#
#   scripts/coverage.sh             frontend + backend UNIT tests (fast)
#   scripts/coverage.sh --full      also run backend INTEGRATION tests
#   scripts/coverage.sh --frontend  frontend only
#   scripts/coverage.sh --backend   backend only
#
# NOTE on accuracy: coverage only reflects the tests you run. In the default (fast)
# mode the backend integration suite is skipped, so code that is exercised *only*
# by integration tests shows up here as uncovered — a false gap. Use --full for the
# trustworthy picture (slower; needs the Docker socket + runs as root in the
# container, per the testcontainers requirement).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTAINER="eneo_devcontainer-eneo-1"
FULL=0
DO_FE=1
DO_BE=1

for arg in "$@"; do
  case "$arg" in
    --full) FULL=1 ;;
    --frontend|--fe) DO_BE=0 ;;
    --backend|--be) DO_FE=0 ;;
    -h|--help) sed -n '2,21p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $arg (try --help)" >&2; exit 1 ;;
  esac
done

if [ "$DO_FE" = 1 ]; then
  echo "▶ Frontend coverage (vitest) …"
  ( cd "$ROOT/frontend/apps/web" && bun run test:coverage )
fi

if [ "$DO_BE" = 1 ]; then
  docker context use orbstack >/dev/null 2>&1 || true
  if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
    echo "✗ backend devcontainer '$CONTAINER' is not running — start it, or use --frontend." >&2
    exit 1
  fi
  # uv lives at /home/vscode/.local/bin; keep it on PATH and point HOME at vscode.
  ENV_PREFIX="export PATH=/home/vscode/.local/bin:\$PATH HOME=/home/vscode"
  if [ "$FULL" = 1 ]; then
    echo "▶ Backend coverage (pytest: unit + integration) …"
    # Integration tests use testcontainers → need root + the Docker socket.
    docker exec -u root -i "$CONTAINER" bash -c \
      "$ENV_PREFIX TESTCONTAINERS_RYUK_DISABLED=true DOCKER_HOST=unix:///var/run/docker.sock && cd /workspace/backend && \
       uv run pytest -n 2 -m 'not integration' --cov=src/intric --cov-report= tests/ && \
       uv run pytest -n 2 -m integration --cov=src/intric --cov-append \
         --cov-report=term-missing:skip-covered --cov-report=html --cov-report=json tests/integration/"
  else
    echo "▶ Backend coverage (pytest: unit only) …"
    docker exec -u vscode -i "$CONTAINER" bash -c \
      "$ENV_PREFIX && cd /workspace/backend && \
       uv run pytest -n 2 -m 'not integration' --cov=src/intric \
         --cov-report=term-missing:skip-covered --cov-report=html --cov-report=json tests/"
  fi
fi

python3 "$ROOT/scripts/coverage_gaps.py"

echo "Open the full, clickable reports:"
[ "$DO_FE" = 1 ] && echo "  frontend:  $ROOT/frontend/apps/web/coverage/index.html"
[ "$DO_BE" = 1 ] && echo "  backend:   $ROOT/backend/htmlcov/index.html"
