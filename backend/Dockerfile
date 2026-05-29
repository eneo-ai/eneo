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

# Production stage
FROM python:3.11-slim-bookworm

# Runtime dependencies:
# - ffmpeg/libmagic1 support existing audio and file type detection paths.
# - fontconfig/fonts/harfbuzz/pango support WeasyPrint PDF rendering.
RUN apt-get update && apt-get install -y \
    ffmpeg \
    fontconfig \
    fonts-dejavu-core \
    libharfbuzz-subset0 \
    libmagic1 \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    && rm -rf /var/lib/apt/lists/*

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
