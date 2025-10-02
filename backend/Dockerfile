FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim AS builder

# Install system dependencies
RUN apt-get update && apt-get install -y ffmpeg libmagic1 && rm -rf /var/lib/apt/lists/*

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
FROM python:3.11-slim

# Install runtime dependencies
RUN apt-get update && apt-get install -y ffmpeg libmagic1 && rm -rf /var/lib/apt/lists/*

# Copy venv and tiktoken from builder
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /tiktoken /tiktoken
COPY --from=builder /app /app

# Set PATH to use venv and environment variables
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    TIKTOKEN_CACHE_DIR=/tiktoken

WORKDIR /app

# Run as unprivileged user
USER 1000

CMD ["sh", "-c", "./run.sh"]
