# syntax=docker/dockerfile:1
# Eneo tool runtime: the bundled, isolated MCP provider. No database, no console, no
# configuration files; everything comes from the environment (see README.md).
FROM oven/bun:1.3.14-slim AS deps
WORKDIR /app
COPY package.json bun.lock ./
RUN --mount=type=cache,target=/root/.bun/install/cache \
    bun install --frozen-lockfile --production

FROM oven/bun:1.3.14-slim
ARG VERSION=0.0.0-dev
ARG GIT_SHA=unknown
ARG SOURCE_URL=
LABEL org.opencontainers.image.source="${SOURCE_URL}" \
      org.opencontainers.image.url="${SOURCE_URL}" \
      org.opencontainers.image.title="Eneo tool runtime" \
      org.opencontainers.image.description="Bundled isolated MCP tools for Eneo" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${GIT_SHA}"
USER root
# coreutils provides /usr/bin/timeout, the external watchdog for sandbox children.
# fonts-dejavu-core is embedded in generated PDFs (Swedish characters included).
# The upgrade picks up Debian security fixes the base image has not yet absorbed.
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends coreutils fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
ENV NODE_ENV=production \
    APP_VERSION=${VERSION}
COPY --from=deps /app/node_modules ./node_modules
COPY package.json tsconfig.json ./
COPY src ./src
USER bun
EXPOSE 3010
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
  CMD ["bun", "-e", "const r=await fetch('http://127.0.0.1:3010/health/ready');process.exit(r.ok?0:1)"]
CMD ["bun", "src/main.ts"]
