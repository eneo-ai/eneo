# Stage 1: Builder. Bun installs dependencies and runs the package scripts;
# vite itself runs under Node, as it does in CI and on developer machines.
# Without a Node binary, Bun runs vite on its own JavaScript runtime, which
# has crashed (1.3.0) or starved the CI runner (1.3.14) on this build.
FROM node:22-bookworm-slim AS builder
COPY --from=oven/bun:1.3.14-slim /usr/local/bin/bun /usr/local/bin/bun

WORKDIR /app
COPY . .

ENV NODE_OPTIONS=--max-old-space-size=8192

# Install dependencies with Bun (uses frozen lockfile)
RUN bun install --frozen-lockfile

# Build the application
RUN bun run build

# Stage 2: Production runtime using Node.js
# Required ENV vars, see README.md
# ORIGIN, JWT_SECRET, PUBLIC_API_URL
FROM node:20-bullseye-slim AS runner

WORKDIR /app
COPY --from=builder /app/apps/web/build build/
COPY --from=builder /app/apps/web/package.json .

EXPOSE 3000
USER node
ENV NODE_ENV="production"
CMD ["node", "build"]
