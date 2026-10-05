# Stage 1: Builder. Bun installs dependencies and runs the package scripts;
# vite itself runs under Node, as it does in CI and on developer machines.
# Without a Node binary, Bun runs vite on its own JavaScript runtime, which
# has crashed (1.3.0) or starved the CI runner (1.3.14) on this build.
FROM node:22-trixie-slim AS builder
COPY --from=oven/bun:1.3.14-slim /usr/local/bin/bun /usr/local/bin/bun

WORKDIR /app
COPY . .

ENV NODE_OPTIONS=--max-old-space-size=8192

# Install dependencies with Bun (uses frozen lockfile)
RUN bun install --frozen-lockfile

# This image ships apps/web; web-next has its own Dockerfile and build context.
RUN bun run --filter @eneo/ui build && bun run --filter @eneo/web build

# Stage 2: Production runtime using Node.js
# Required ENV vars, see README.md
# ORIGIN, JWT_SECRET, PUBLIC_API_URL
FROM gcr.io/distroless/nodejs22-debian13:nonroot@sha256:ec2313763dd43931543bd03830466e0c409ce73a487e8d46f10db72d3b816c1c AS runner
# Keep glibc aligned with the builder; runtime has no shell/package managers.
# Explicit PATH also supports deployment probes that execute `node` directly.
ENV PATH="/nodejs/bin:$PATH"

WORKDIR /app
# No node_modules in this image: adapter-node bundles apps/web devDependencies into build/,
# while server-side imports of packages under `dependencies` stay external and fail to resolve.
# Keep runtime libraries in devDependencies.
COPY --from=builder /app/apps/web/build build/
COPY --from=builder /app/apps/web/package.json .

EXPOSE 3000
USER 1000:1000
ENV NODE_ENV="production"
CMD ["build"]
