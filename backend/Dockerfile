ARG APP_VERSION=0.0.0-dev
ARG APP_REVISION=unknown
# web-build bundles the Vite app. A stack that leaves WEB_APP_ENABLED off (the
# Svelte E2E) passes no-web-app and skips that build.
ARG WEB_APP_STAGE=web-build

FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim AS builder

# Build dependencies for packages that may compile from source on some
# architectures, for example psutil on the current builder image.
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Set uv optimizations
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Copy dependency files for optimal layer caching
COPY pyproject.toml uv.lock ./

# Create venv and install dependencies only (optimal caching)
RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked \
    uv venv /app/.venv && \
    uv sync --frozen --no-dev --no-editable --no-install-project

# Copy application code
COPY . .

# Install the project itself
RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked \
    uv sync --frozen --no-dev --no-editable

# Handle tiktoken cache
ENV TIKTOKEN_CACHE_DIR=/tiktoken
RUN mkdir -p /tiktoken
ADD --chmod=644 https://openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken /tiktoken/9b5ad71b2ce5302211f9c61530b329a4922fc6a4

# The Vite app served by FastAPI when WEB_APP_ENABLED is enabled.
# Build from the repository root with the required named frontend context:
# docker buildx build --build-context web=./frontend backend
FROM node:22.23.4-bookworm-slim AS web-build
ARG BUILDKIT_SBOM_SCAN_STAGE=true
COPY --from=oven/bun:1.4.4 /usr/local/bin/bun /usr/local/bin/bun
WORKDIR /repo

# Frozen workspace installation needs every member manifest and its patches.
COPY --from=web package.json bun.lock bunfig.toml ./
COPY --from=web apps/web-next/package.json apps/web-next/package.json
COPY --from=web apps/web/package.json apps/web/package.json
COPY --from=web apps/docs-site/package.json apps/docs-site/package.json
COPY --from=web packages ./packages
COPY --from=web patches ./patches
RUN bun install --frozen-lockfile --ignore-scripts

COPY --from=web apps/web-next ./apps/web-next
WORKDIR /repo/apps/web-next
ARG APP_VERSION
ARG APP_REVISION
RUN bun run --cwd /repo/packages/widget-loader build
RUN mkdir -p /repo/packages/widget-loader/releases
RUN npm run build:vite

FROM python:3.11-slim-bookworm AS no-web-app
RUN mkdir -p /repo/apps/web-next/dist /repo/apps/web-next/node_modules/.cache \
    && echo '{}' > /repo/apps/web-next/node_modules/.cache/vite-bundle-report.json
RUN mkdir -p /repo/packages/widget-loader/dist /repo/packages/widget-loader/releases

FROM ${WEB_APP_STAGE} AS web-app

# Production stage
FROM python:3.11-slim-bookworm

# Runtime dependencies: ffmpeg/libsndfile1 support audio; libmagic1 supports
# file type detection. Documents are rendered by the tool runtime image.
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libmagic1 \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

# Copy venv and tiktoken from builder
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /tiktoken /tiktoken
COPY --from=builder /app /app
COPY --from=web-app /repo/apps/web-next/dist /app/web-dist
COPY --from=web-app /repo/packages/widget-loader/dist /app/widget-loader/dist
COPY --from=web-app /repo/packages/widget-loader/releases /app/widget-loader/releases
# Browser tests resolve chunks from this exact build. Keep the map outside
# web-dist so module metadata is not served by the web app.
COPY --from=web-app /repo/apps/web-next/node_modules/.cache/vite-bundle-report.json /app/web-bundle-report.json

# Set PATH to use venv and environment variables.
# LITELLM_LOCAL_MODEL_COST_MAP keeps LiteLLM on the model and price catalog
# bundled with the pinned version; otherwise every start fetches it from
# LiteLLM's GitHub main branch.
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    TIKTOKEN_CACHE_DIR=/tiktoken \
    LITELLM_LOCAL_MODEL_COST_MAP=True

# OTel service version — pass --build-arg OTEL_SERVICE_VERSION=<version> at
# build time so it surfaces as resource.service.version in every log line and
# span. CI passes the release tag / branch-sha here. Defaults to "unknown" for
# local builds that don't supply it.
ARG OTEL_SERVICE_VERSION=unknown
ENV OTEL_SERVICE_VERSION=${OTEL_SERVICE_VERSION}

WORKDIR /app

# Run as unprivileged user
USER 1000

# Exec form: init's SIGTERM reaches run.sh, which execs arq or gunicorn, so
# they drain. Under `sh -c` the shell forks run.sh and the signal stops there.
CMD ["./run.sh"]
ARG APP_VERSION
ARG APP_REVISION
ENV APP_VERSION=${APP_VERSION} APP_REVISION=${APP_REVISION}
