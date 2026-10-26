# Stage 1: Builder. Bun installs dependencies and runs the package scripts;
# vite itself runs under Node, as it does in CI and on developer machines.
# Without a Node binary, Bun runs vite on its own JavaScript runtime, which
# has crashed (1.3.0) or starved the CI runner (1.3.14) on this build.
FROM node:22.23.4-bookworm-slim AS builder
COPY --from=oven/bun:1.4.4-slim /usr/local/bin/bun /usr/local/bin/bun

WORKDIR /app
ARG APP_VERSION=0.0.0-dev
ARG APP_REVISION=unknown
ENV APP_VERSION=${APP_VERSION} APP_REVISION=${APP_REVISION}
COPY . .

# Install dependencies with Bun (uses frozen lockfile)
RUN bun install --frozen-lockfile

# This image ships apps/web; web-next has its own Dockerfile and build context.
# Match frontend CI's heap budget for adapter-node bundling.
RUN bun run --filter @eneo/ui build && NODE_OPTIONS=--max-old-space-size=8192 bun run --filter @eneo/web build

# Stage 2: Production runtime using Node.js
# Required ENV vars, see README.md
# ORIGIN, JWT_SECRET, PUBLIC_API_URL
FROM node:22.23.4-bookworm-slim AS runner
# The runtime only executes node. Drop the bundled package managers: their vendored
# dependencies lag behind advisories and would fail the release image vulnerability gate.
RUN rm -rf /usr/local/lib/node_modules /usr/local/bin/npm /usr/local/bin/npx \
    /usr/local/bin/corepack /usr/local/bin/yarn /usr/local/bin/yarnpkg /opt/yarn-v*

WORKDIR /app
# No node_modules in this image: adapter-node bundles apps/web devDependencies into build/,
# while server-side imports of packages under `dependencies` stay external and fail to resolve.
# Keep runtime libraries in devDependencies.
COPY --from=builder /app/apps/web/build build/
COPY --from=builder /app/apps/web/package.json .

EXPOSE 3000
USER node
ENV NODE_ENV="production"
CMD ["node", "build"]

ARG APP_VERSION=0.0.0-dev
ARG APP_REVISION=unknown
ENV APP_VERSION=${APP_VERSION} APP_REVISION=${APP_REVISION}
