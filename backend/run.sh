#!/bin/bash

set -e

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
