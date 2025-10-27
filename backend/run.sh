#!/bin/bash

set -e

# Default start
function start_backend_default() {
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
}

# new start
function start_backend_arq() {
  arq src.intric.worker.arq.WorkerSettings
}

# worker start
function start_worker_default() {
  poetry run arq intric.worker.arq.WorkerSettings
}


case "${START_ROLE}" in
    ""|"DEFAULT")
        start_backend_default
        ;;
    "BACKEND_ARQ")
        start_backend_arq
        ;;
    "WORKER_DEFAULT")
        start_worker_default
        ;;
esac



