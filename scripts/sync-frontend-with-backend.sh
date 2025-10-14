#!/bin/bash

set -euo pipefail

# Frontend Build with Backend Version Synchronization

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_IMAGE=""
BUILD_VERSION=""
REGISTRY="${REGISTRY:-ghcr.io}"
BACKEND_IMAGE_NAME="${BACKEND_IMAGE_NAME:-eneo-ai/eneo-backend}"

# Cleanup function
cleanup() {
    # Stop any temp backend containers
    local containers
    containers=$(docker ps -q --filter "name=temp-backend-" 2>/dev/null || true)

    if [[ -n "$containers" ]]; then
        echo "Stopping backend container..." >&2
        docker stop $containers 2>/dev/null || true
    fi
}
trap cleanup EXIT SIGINT SIGTERM

# Determine backend image to use
determine_backend_image() {
    local image_spec="$1"

    if [[ "$image_spec" =~ : ]] || docker image inspect "$image_spec" >/dev/null 2>&1; then
        # Full image name with tag OR local image exists
        BACKEND_IMAGE="$image_spec"
    else
        # Just a tag, use default registry/image name
        BACKEND_IMAGE="$REGISTRY/$BACKEND_IMAGE_NAME:$image_spec"
    fi

    echo "Using backend image: $BACKEND_IMAGE"
}

# Check if container is running and healthy
check_container_health() {
    local container_name="$1"
    local backend_port="$2"

    # Check if container exists and is running
    if ! docker ps --filter "name=$container_name" --filter "status=running" --format "{{.Names}}" | grep -q "^${container_name}$"; then
        echo "ERROR: Container $container_name is not running" >&2
        echo "Container status:" >&2
        docker ps -a --filter "name=$container_name" >&2
        echo "Container logs (last 20 lines):" >&2
        docker logs "$container_name" 2>&1 | tail -20 >&2
        return 1
    fi

    # Check if the API endpoint is responding
    if ! curl -s --max-time 5 "http://localhost:$backend_port/openapi.json" >/dev/null 2>&1; then
        echo "WARNING: Container $container_name is running but API endpoint not responding" >&2
        echo "Container logs (last 10 lines):" >&2
        docker logs "$container_name" 2>&1 | tail -10 >&2
        return 1
    fi

    return 0
}


# Update intric-js types and version
update_intric_js() {
    local backend_port="$1"
    local intric_js_dir="$SCRIPT_DIR/frontend/packages/intric-js"

    if [[ ! -d "$intric_js_dir" ]]; then
        echo "intric-js directory not found, skipping"
        return 0
    fi

    echo "Updating intric-js types from backend version $BUILD_VERSION..."
    cd "$intric_js_dir"

    # Generate types from backend
    if ! command -v bun >/dev/null 2>&1; then
        echo "Error: bun is required but not found"
        exit 1
    fi

    echo "Installing dependencies with bun..."
    if ! bun install; then
        echo "ERROR: bun install failed"
        exit 1
    fi

    echo "Generating types from backend..."
    if ! INTRIC_BACKEND_URL="http://localhost:$backend_port" bun run update; then
        echo "ERROR: Failed to generate types from backend"
        echo "Checking if container is still healthy..."
        # Use global container name that should be available
        if [[ -n "$CONTAINER_NAME_FOR_LOGS" ]]; then
            check_container_health "$CONTAINER_NAME_FOR_LOGS" "$backend_port"
        fi
        echo "bun run update failed, this may be due to container issues"
        exit 1
    fi

    echo "intric-js types updated"
}

# Update web app version
update_web_app_version() {
    local web_app_dir="$SCRIPT_DIR/frontend/apps/web"

    if [[ ! -d "$web_app_dir" ]]; then
        echo "Web app directory not found, skipping"
        return 0
    fi

    echo "Updating web app version to $BUILD_VERSION..."
    cd "$web_app_dir"

    # Update version in package.json
    jq --arg version "$BUILD_VERSION" '.version = $version' package.json > package.json.tmp
    mv package.json.tmp package.json
    echo "Updated web app version to: $BUILD_VERSION"
}

# Main function
main() {
    local backend_image_tag="${1:-}"

    if [[ -z "$backend_image_tag" ]]; then
        echo "Usage: $0 <backend-image>"
        echo "Examples:"
        echo "  $0 eneo-backend:latest"
        echo "  $0 v1.2.3"
        echo "  $0 ghcr.io/eneo-ai/eneo-backend:v1.2.3"
        exit 1
    fi

    echo "Starting frontend synchronization with backend..."

    determine_backend_image "$backend_image_tag"

    # Inline container startup to avoid subshell issues in GitHub Actions
    echo "Starting backend container..." >&2

    # Pull image if needed
    if ! docker image inspect "$BACKEND_IMAGE" >/dev/null 2>&1; then
        echo "Pulling backend image..." >&2
        docker pull "$BACKEND_IMAGE"
    fi

    # Use a fixed port for CI simplicity
    local backend_port=8080
    echo "Using port $backend_port for backend..." >&2

    # Start container
    local container_name="temp-backend-$$"
    # Make container name globally available for error handling
    export CONTAINER_NAME_FOR_LOGS="$container_name"
    echo "Starting backend on port $backend_port..." >&2

    docker run -d --rm \
        --platform linux/amd64 \
        --name "$container_name" \
        -p "$backend_port:8000" \
        -e OPENAPI_ONLY_MODE=true \
        -e OPENAI_API_KEY=dummy \
        -e ANTHROPIC_API_KEY=dummy \
        -e POSTGRES_USER=dummy \
        -e POSTGRES_HOST=dummy \
        -e POSTGRES_PASSWORD=dummy \
        -e POSTGRES_PORT=5432 \
        -e POSTGRES_DB=dummy \
        -e REDIS_HOST=dummy \
        -e REDIS_PORT=6379 \
        -e UPLOAD_FILE_TO_SESSION_MAX_SIZE=1000000 \
        -e UPLOAD_IMAGE_TO_SESSION_MAX_SIZE=1000000 \
        -e UPLOAD_MAX_FILE_SIZE=1000000 \
        -e TRANSCRIPTION_MAX_FILE_SIZE=1000000 \
        -e MAX_IN_QUESTION=1 \
        -e API_PREFIX=/api/v1 \
        -e API_KEY_LENGTH=64 \
        -e API_KEY_HEADER_NAME=dummy \
        -e JWT_AUDIENCE=dummy \
        -e JWT_ISSUER=dummy \
        -e JWT_EXPIRY_TIME=86000 \
        -e JWT_ALGORITHM=HS256 \
        -e JWT_SECRET=dummy \
        -e JWT_TOKEN_PREFIX=dummy \
        -e URL_SIGNING_KEY=dummy \
        -e NUM_WORKERS=1 \
        "$BACKEND_IMAGE" > /dev/null

    # Wait for backend OpenAPI endpoint to be ready
    echo "Waiting for backend OpenAPI endpoint to be ready..." >&2
    local attempt=0
    while [ $attempt -lt 30 ]; do
        echo "Attempt $((attempt + 1)): Testing http://localhost:$backend_port/openapi.json" >&2
        if curl -s "http://localhost:$backend_port/openapi.json" | jq -e '.info.version' >/dev/null 2>&1; then
            echo "Backend OpenAPI endpoint ready" >&2
            break
        fi
        echo "Backend OpenAPI not ready yet, waiting..." >&2
        sleep 3
        attempt=$((attempt + 1))
    done

    if [ $attempt -eq 30 ]; then
        echo "Backend failed to start" >&2
        echo "Container status:" >&2
        docker ps -a --filter "name=$container_name" >&2
        echo "Container logs:" >&2
        docker logs "$container_name" 2>&1 | tail -20 >&2
        exit 1
    fi

    # Get version from running backend (we already tested this works)
    echo "Extracting version from backend..."
    BUILD_VERSION=$(curl -s "http://localhost:$backend_port/openapi.json" | jq -r '.info.version')
    echo "Backend version: $BUILD_VERSION"

    # Verify version was extracted successfully
    if [[ -z "$BUILD_VERSION" || "$BUILD_VERSION" == "null" ]]; then
        echo "ERROR: Failed to extract version from backend API" >&2
        exit 1
    fi

    update_intric_js "$backend_port"
    update_web_app_version

    echo "Frontend synchronization completed successfully!"
    echo "Backend version: $BUILD_VERSION"
}

main "$@"
