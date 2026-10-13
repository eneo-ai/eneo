#!/usr/bin/env bash
# Diagnostic only: the publication gate continues to use check-application-image.sh.
set -euo pipefail
kind=${1:?backend or frontend}
image=${2:?image}
if [[ "$kind" == frontend ]]; then
  exec timeout 120 bash scripts/check-application-image.sh frontend "$image"
fi
name="eneo-comparison-${GITHUB_RUN_ID:-local}-${GITHUB_JOB:-check}"
cleanup() { docker rm -f "$name" >/dev/null 2>&1 || true; }
trap cleanup EXIT
options=(--name "$name" --network none --cap-drop ALL --security-opt no-new-privileges
  --memory 2g --cpus 1 --entrypoint python
  -e POSTGRES_USER=test -e POSTGRES_PASSWORD=test -e POSTGRES_HOST=localhost
  -e POSTGRES_PORT=5432 -e POSTGRES_DB=test -e REDIS_HOST=localhost -e REDIS_PORT=6379
  -e API_PREFIX=/api/v1 -e API_KEY_LENGTH=64 -e API_KEY_HEADER_NAME=X-API-Key
  -e JWT_AUDIENCE=test -e JWT_ISSUER=test -e JWT_EXPIRY_TIME=3600 -e JWT_ALGORITHM=HS256
  -e JWT_SECRET=image-test-secret-not-for-production -e JWT_TOKEN_PREFIX=Bearer
  -e URL_SIGNING_KEY=image-test-signing-key-at-least-32-bytes -e EXPORT_DIR=/tmp/exports)
status=0
# Keep ABI/launcher checks independent of the audio results so both are recorded.
timeout 120 docker run "${options[@]}" \
  -v "$PWD/backend/scripts/check_runtime.py:/tmp/check_runtime.py:ro" \
  "$image" /tmp/check_runtime.py --portable || status=1
cleanup
timeout 120 docker run "${options[@]}" \
  -v "$PWD/backend/tests/unittests/files/test_audio.py:/tmp/test_audio.py:ro" \
  "$image" /tmp/test_audio.py -v || status=1
exit "$status"
