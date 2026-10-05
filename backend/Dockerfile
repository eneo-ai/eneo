FROM cgr.dev/chainguard/wolfi-base:latest@sha256:9c2092b053779e14c82fb50f77b37bcc38b7d2c83972352d5813280f9d035b03 AS runtime-base
# Maintained glibc packages retain Python 3.11 and the complete audio format set.
# Keep APK metadata: both distribution and upstream CVEs are gated in CI.
RUN apk update && apk upgrade && apk add --no-cache \
    python-3.11 bash ffmpeg-9.0 libmagic libxml2-16 libxslt libstdc++ \
    && rm -rf /var/cache/apk/*

FROM runtime-base AS builder
COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /usr/local/bin/uv
# Link lxml to the maintained system libxml2/libxslt, avoiding a hidden copy in
# the manylinux wheel. Only the builder needs compiler and development headers.
RUN apk add --no-cache build-base python-3.11-dev libxml2-dev libxslt-dev

# Set uv optimizations
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_NO_BINARY_PACKAGE=lxml

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

# Production stage
FROM runtime-base AS runner

# Copy venv and tiktoken from builder
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /tiktoken /tiktoken
COPY --from=builder /app /app

# Set PATH to use venv and environment variables
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    TIKTOKEN_CACHE_DIR=/tiktoken

# OTel service version — pass --build-arg OTEL_SERVICE_VERSION=<version> at
# build time so it surfaces as resource.service.version in every log line and
# span. CI passes the release tag / branch-sha here. Defaults to "unknown" for
# local builds that don't supply it.
ARG OTEL_SERVICE_VERSION=unknown
ENV OTEL_SERVICE_VERSION=${OTEL_SERVICE_VERSION}

WORKDIR /app

# Run as unprivileged user
USER 1000

CMD ["sh", "-c", "./run.sh"]
