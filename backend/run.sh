#!/bin/bash

set -e

# Prefer project virtualenv binaries when available (devcontainer + docker image).
for venv_bin in "/workspace/backend/.venv/bin" "/app/.venv/bin"; do
    if [[ -d "${venv_bin}" ]]; then
        export PATH="${venv_bin}:${PATH}"
        break
    fi
done

# Check if running as worker
if [[ "${RUN_AS_WORKER,,}" == "true" ]]; then
    echo "Starting ARQ worker for background task processing"
    echo "Launching..."
    exec arq src.eneo.worker.arq.WorkerSettings
fi

# Check if running as Celery worker (flows runtime)
if [[ "${RUN_AS_CELERY_WORKER,,}" == "true" ]]; then
    echo "Starting Celery flow worker"
    echo "Launching..."
    exec flow-worker
fi

# Check if running as Celery beat (flows reconciliation scheduler)
if [[ "${RUN_AS_CELERY_BEAT,,}" == "true" ]]; then
    echo "Starting Celery beat for flow reconciliation scheduling"
    echo "Launching..."
    exec flow-beat
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

# keepalive must outlive every client's idle connection pool (Node/undici
# holds SSR sockets ~4s; gunicorn's default is 2s and it sends no
# Keep-Alive hint), otherwise the server closes a socket the client still
# considers live and an in-flight SSR fetch dies with ECONNRESET.
exec gunicorn \
    src.eneo.server.main:app \
    --workers $workers \
    --worker-class uvicorn.workers.UvicornWorker \
    --keep-alive 75 \
    --bind 0.0.0.0:8000
