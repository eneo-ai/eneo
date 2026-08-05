#!/bin/bash

set -e

# Check if running as worker
if [[ "${RUN_AS_WORKER,,}" == "true" ]]; then
    echo "Starting ARQ worker for background task processing"
    echo "Launching..."
    exec arq src.eneo.worker.arq.WorkerSettings
fi

# Skip Alembic migrations in OpenAPI-only mode
if [[ "${OPENAPI_ONLY_MODE,,}" != "true" ]]; then
    alembic upgrade head
fi

if [[ -z "${NUM_WORKERS}" ]]; then
    workers=3
else
    workers=$NUM_WORKERS
fi

echo "Starting Eneo backend with $workers workers"

# Loopback MCP servers (/internal-mcp) are served by this same process, which
# binds :8000 below. The config default targets the uvicorn dev port (8123),
# so pin the packaged default here unless the deployment overrides it.
export INTERNAL_MCP_BASE_URL="${INTERNAL_MCP_BASE_URL:-http://localhost:8000}"

# keepalive must outlive every client's idle connection pool (Node/undici
# holds SSR sockets ~4s; gunicorn's default is 2s and it sends no
# Keep-Alive hint), otherwise the server closes a socket the client still
# considers live and an in-flight SSR fetch dies with ECONNRESET.
exec gunicorn src.eneo.server.main:app --workers $workers --worker-class uvicorn.workers.UvicornWorker --keep-alive 75 --bind 0.0.0.0:8000
