# Stage 1: Builder using Bun
FROM oven/bun:1.2.23-slim AS builder

WORKDIR /app
COPY . .

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
