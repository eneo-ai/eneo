#!/usr/bin/env bash
# Exercise the shipped artifact, with no provider credentials or external network.
set -euo pipefail
kind=${1:?backend, frontend or web-next}
image=${2:?candidate image}
repo=$(cd "$(dirname "$0")/.." && pwd)
if [[ "$kind" == backend ]]; then
  docker run --rm --network none --cap-drop ALL --security-opt no-new-privileges \
    --memory 2g --cpus 1 --entrypoint python \
    -e POSTGRES_USER=test -e POSTGRES_PASSWORD=test -e POSTGRES_HOST=localhost \
    -e POSTGRES_PORT=5432 -e POSTGRES_DB=test -e REDIS_HOST=localhost -e REDIS_PORT=6379 \
    -e API_PREFIX=/api/v1 -e API_KEY_LENGTH=64 -e API_KEY_HEADER_NAME=X-API-Key \
    -e JWT_AUDIENCE=test -e JWT_ISSUER=test -e JWT_EXPIRY_TIME=3600 -e JWT_ALGORITHM=HS256 \
    -e JWT_SECRET=image-test-secret-not-for-production -e JWT_TOKEN_PREFIX=Bearer \
    -e URL_SIGNING_KEY=image-test-signing-key-at-least-32-bytes -e EXPORT_DIR=/tmp/exports \
    -v "$repo/backend/tests/unittests/files/test_audio.py:/tmp/test_audio.py:ro" \
    "$image" /tmp/test_audio.py
  docker run --rm --network none --memory 1g --cpus 1 --entrypoint python \
    -v "$repo/backend/scripts/check_runtime.py:/tmp/check_runtime.py:ro" \
    "$image" /tmp/check_runtime.py
  exit 0
fi
case "$kind" in frontend|web-next) ;; *) echo "Unknown application: $kind" >&2; exit 2 ;; esac
container=
cleanup() {
  status=$?
  if [[ -n "$container" ]]; then
    if [[ "$status" != 0 ]]; then docker logs --tail 80 "$container" >&2; fi
    docker rm -f "$container" >/dev/null
  fi
}
trap cleanup EXIT
container=$(docker run -d --network none --cap-drop ALL --security-opt no-new-privileges \
  --memory 1g --cpus 1 \
  -e ORIGIN=http://localhost:3000 -e APP_ORIGIN=http://localhost:3000 \
  -e ENEO_BACKEND_URL=http://127.0.0.1:8123 -e ENEO_BACKEND_SERVER_URL=http://127.0.0.1:8123 \
  -e JWT_SECRET=image-test-secret-not-for-production \
  -e SESSION_SECRET=image-test-session-secret-not-for-production "$image")
ready=0
for _ in $(seq 1 40); do
  if docker exec "$container" node -e \
    "fetch('http://127.0.0.1:3000/healthz').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"; then
    ready=1
    break
  fi
  sleep 1
done
[[ "$ready" == 1 ]]
if [[ "$kind" == web-next ]]; then
  # Exercises Sharp, the image endpoint and its on-disk cache as the runtime UID.
  docker exec "$container" node -e \
    "fetch('http://127.0.0.1:3000/_next/image?url=%2Feneo_pwa_logo.png&w=64&q=75').then(async r=>{if(!r.ok||!r.headers.get('content-type')?.startsWith('image/')||(await r.arrayBuffer()).byteLength===0)process.exit(1)}).catch(()=>process.exit(1))"
fi
