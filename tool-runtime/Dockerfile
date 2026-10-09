# syntax=docker/dockerfile:1
# Eneo tool runtime: the bundled, isolated MCP provider. No database, no console, no
# configuration files; everything comes from the environment (see README.md).
FROM oven/bun:1.3.14-slim AS deps
WORKDIR /app
COPY package.json bun.lock ./
RUN --mount=type=cache,target=/root/.bun/install/cache \
    bun install --frozen-lockfile --production

# The tool views (MCP Apps) are built into single pages here; the runtime only reads them, so
# React, Astryx and the bundler never reach the final image.
FROM oven/bun:1.3.14-slim AS views
WORKDIR /app
COPY package.json bun.lock ./
RUN --mount=type=cache,target=/root/.bun/install/cache \
    bun install --frozen-lockfile
COPY tsconfig.json ./
COPY scripts ./scripts
COPY src ./src
RUN bun run build:views

# landrun confines every sandbox child with Landlock before it starts (see src/sandbox.ts).
# Built from source at a pinned version, which the Go checksum database verifies; keep it in
# step with the build:landrun script in package.json.
FROM --platform=$BUILDPLATFORM golang:1.27-bookworm AS landrun
ARG TARGETARCH
RUN CGO_ENABLED=0 GOARCH=$TARGETARCH \
    go install github.com/zouuup/landrun/cmd/landrun@v0.1.17 \
    && find /go/bin -name landrun -type f -exec cp {} /landrun \;

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
# PDFs are laid out by WeasyPrint (scripts/render_pdf.py) in a Python venv at /opt/pdf, which
# needs pango and fontconfig. The fonts are what documents embed: DejaVu, Liberation, and
# Carlito and Caladea, metric-compatible with the Calibri and Cambria of Word templates.
# The upgrade picks up Debian security fixes the base image has not yet absorbed.
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends \
        coreutils python3 python3-venv \
        libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libharfbuzz-subset0 fontconfig \
        fonts-dejavu-core fonts-liberation fonts-crosextra-carlito fonts-crosextra-caladea \
    && rm -rf /var/lib/apt/lists/* \
    && fc-cache -f
COPY scripts/requirements-pdf.txt /tmp/requirements-pdf.txt
RUN python3 -m venv /opt/pdf \
    && /opt/pdf/bin/pip install --no-cache-dir --require-hashes -r /tmp/requirements-pdf.txt \
    && rm /tmp/requirements-pdf.txt
WORKDIR /app
ENV NODE_ENV=production \
    APP_VERSION=${VERSION} \
    APP_REVISION=${GIT_SHA}
COPY --from=landrun /landrun /usr/local/bin/landrun
COPY --from=deps /app/node_modules ./node_modules
COPY package.json tsconfig.json ./
COPY src ./src
COPY scripts/render_pdf.py ./scripts/render_pdf.py
COPY --from=views /app/dist ./dist
USER bun
EXPOSE 3010
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
  CMD ["bun", "-e", "const r=await fetch('http://127.0.0.1:3010/health/ready');process.exit(r.ok?0:1)"]
CMD ["bun", "src/main.ts"]
