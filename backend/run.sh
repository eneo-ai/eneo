#!/bin/bash

set -e

# Check if running as worker
if [[ "${RUN_AS_WORKER,,}" == "true" ]]; then
    echo "Starting ARQ worker for background task processing"
    echo "Launching... Go, intric.ai worker!"
    exec arq src.intric.worker.arq.WorkerSettings
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

echo "Starting intric.ai with $workers workers"
echo "Launching... Go, intric.ai!"

exec gunicorn src.intric.server.main:app --workers $workers --worker-class uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
