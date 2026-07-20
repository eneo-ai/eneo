#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 2 ]]; then
    echo "Usage: $0 <image-digest-reference> <linux-platform>" >&2
    exit 2
fi

image_ref="$1"
platform="$2"
curl_image="${CURL_IMAGE:?Set CURL_IMAGE to a pinned curl image digest}"

if [[ ! "$image_ref" =~ @sha256:[0-9a-f]{64}$ ]]; then
    echo "Image must be supplied by immutable digest: $image_ref" >&2
    exit 2
fi
if [[ "$platform" != "linux/amd64" && "$platform" != "linux/arm64" ]]; then
    echo "Unsupported smoke-test platform: $platform" >&2
    exit 2
fi
if [[ ! "$curl_image" =~ @sha256:[0-9a-f]{64}$ ]]; then
    echo "CURL_IMAGE must be supplied by immutable digest: $curl_image" >&2
    exit 2
fi

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
deployment_compose="$repository_root/docs/deployment/docker-compose.yml"
work_directory="$(mktemp -d)"
project_name="eneo-object-content-smoke-${GITHUB_RUN_ID:-local}-${GITHUB_RUN_ATTEMPT:-0}-$$"
network_name="${project_name}_object_content_net"

compose=(
    docker compose
    --project-name "$project_name"
    --file "$work_directory/docker-compose.yml"
    --file "$work_directory/smoke.override.yml"
)

cleanup() {
    "${compose[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
    rm -rf "$work_directory"
}
trap cleanup EXIT

cp "$deployment_compose" "$work_directory/docker-compose.yml"
touch \
    "$work_directory/env_backend.env" \
    "$work_directory/env_db.env" \
    "$work_directory/env_frontend.env"
printf '%s\n' \
    'services:' \
    '  object-content:' \
    "    platform: $platform" \
    >"$work_directory/smoke.override.yml"

export ENEO_SEAWEEDFS_IMAGE="$image_ref"
export OBJECT_CONTENT_ACCESS_KEY_ID="eneo-reference-smoke"
export OBJECT_CONTENT_SECRET_ACCESS_KEY="reference-smoke-only-7f9b1c4a"
export OBJECT_CONTENT_BUCKET="eneo-reference-smoke"
export OBJECT_CONTENT_DEPLOYMENT_ID="1fdc7506-960a-4fcb-9768-26cc73f95e36"

valid_curl_config="$work_directory/curl-valid.conf"
invalid_curl_config="$work_directory/curl-invalid.conf"
printf 'aws-sigv4 = "aws:amz:local:s3"\nuser = "%s:%s"\n' \
    "$OBJECT_CONTENT_ACCESS_KEY_ID" "$OBJECT_CONTENT_SECRET_ACCESS_KEY" \
    >"$valid_curl_config"
printf 'aws-sigv4 = "aws:amz:local:s3"\nuser = "invalid:invalid"\n' \
    >"$invalid_curl_config"
chmod 0600 "$valid_curl_config" "$invalid_curl_config"

docker pull --platform "$platform" "$curl_image" >/dev/null

container_curl() {
    docker run \
        --rm \
        --platform "$platform" \
        --network "$network_name" \
        --user "$(id -u):$(id -g)" \
        --read-only \
        --cap-drop ALL \
        --security-opt no-new-privileges:true \
        --volume "$work_directory:/work" \
        "$curl_image" \
        "$@"
}

start_store() {
    "${compose[@]}" up --detach --no-deps object-content
    endpoint="http://object-content:8333"

    for attempt in {1..90}; do
        if container_curl --fail --silent "$endpoint/status" >/dev/null 2>&1; then
            return 0
        fi
        if [[ "$attempt" -eq 90 ]]; then
            "${compose[@]}" logs object-content >&2
            echo "Reference object-content service did not become ready." >&2
            return 1
        fi
        sleep 1
    done
}

assert_runtime_hardening() {
    local container_id
    container_id="$("${compose[@]}" ps --quiet object-content)"

    [[ "$(docker inspect --format '{{.Config.User}}' "$container_id")" == "65532:65532" ]]
    [[ "$(docker inspect --format '{{.HostConfig.ReadonlyRootfs}}' "$container_id")" == "true" ]]
    [[ "$(docker inspect --format '{{json .HostConfig.CapDrop}}' "$container_id")" == '["ALL"]' ]]
    [[ "$(docker inspect --format '{{json .HostConfig.SecurityOpt}}' "$container_id")" == '["no-new-privileges:true"]' ]]
    [[ "$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Type}}{{end}}{{end}}' "$container_id")" == "volume" ]]
}

signed_curl() {
    container_curl \
        --config /work/curl-valid.conf \
        --fail-with-body \
        --silent \
        --show-error \
        "$@"
}

start_store
assert_runtime_hardening
signed_curl "$endpoint/$OBJECT_CONTENT_BUCKET" >/dev/null

invalid_status="$(container_curl \
    --config /work/curl-invalid.conf \
    --output /dev/null \
    --silent \
    --write-out '%{http_code}' \
    "$endpoint/$OBJECT_CONTENT_BUCKET")"
if [[ "$invalid_status" != "403" ]]; then
    echo "Invalid object-content credentials returned HTTP $invalid_status, expected 403." >&2
    exit 1
fi

payload="$work_directory/payload.bin"
download="$work_directory/download.bin"
printf 'Eneo reference object-content persistence smoke\n' >"$payload"
object_url="$endpoint/$OBJECT_CONTENT_BUCKET/reference-bootstrap-smoke"
signed_curl --request PUT --upload-file /work/payload.bin "$object_url" >/dev/null
signed_curl --output /work/download.bin "$object_url"
cmp "$payload" "$download"

"${compose[@]}" stop object-content
"${compose[@]}" rm --force object-content
start_store
signed_curl --output /work/download.bin "$object_url"
cmp "$payload" "$download"

signed_curl --request DELETE "$object_url" >/dev/null
deleted_status="$(container_curl \
    --config /work/curl-valid.conf \
    --output /dev/null \
    --silent \
    --write-out '%{http_code}' \
    "$object_url")"
if [[ "$deleted_status" != "404" ]]; then
    echo "Deleted object returned HTTP $deleted_status, expected 404." >&2
    exit 1
fi

echo "Reference object-content bootstrap smoke passed for $platform."
