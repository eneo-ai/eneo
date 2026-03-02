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
    exec arq src.intric.worker.arq.WorkerSettings
fi

# Check if running as Celery worker (flows runtime)
if [[ "${RUN_AS_CELERY_WORKER,,}" == "true" ]]; then
    queue="${FLOW_CELERY_QUEUE:-flows.execute}"
    echo "Starting Celery flow worker on queue: ${queue}"
    echo "Launching..."
    python - <<'PY'
import importlib.util
import sys

missing = [
    module_name
    for module_name in ("fpdf", "docx")
    if importlib.util.find_spec(module_name) is None
]
if missing:
    print(
        "Missing flow runtime dependencies in worker environment: "
        + ", ".join(missing),
        file=sys.stderr,
    )
    print(
        "Install backend dependencies (for example `uv sync`) or rebuild the backend image "
        "before starting the Celery flow worker.",
        file=sys.stderr,
    )
    raise SystemExit(1)
PY
    exec celery -A src.intric.flows.runtime.celery_app:celery_app worker --loglevel=INFO --queues "${queue}"
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

exec gunicorn src.intric.server.main:app --workers $workers --worker-class uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
