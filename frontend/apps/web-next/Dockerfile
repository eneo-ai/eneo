# Eneo web-next production image.
# Build with Bun (matches local tooling), run on Node 20 slim using Next's
# standalone output (next.config.ts sets output: "standalone").
#
#   docker build -f frontend/apps/web-next/Dockerfile -t eneo-web-next ./frontend
#
# The build context is ./frontend so the bun workspace (packages/*) resolves.

# ---- deps + build -----------------------------------------------------------
FROM oven/bun:1 AS builder
WORKDIR /repo

# Workspace manifests first for a cached install layer.
COPY package.json bun.lock ./
COPY apps/web-next/package.json apps/web-next/package.json
COPY packages ./packages
RUN bun install --frozen-lockfile

# App source.
COPY apps/web-next ./apps/web-next
WORKDIR /repo/apps/web-next

# A throwaway env so env.ts (zod-validated at import during page-data
# collection) passes the build; real values are injected at runtime.
ENV ENEO_BACKEND_URL=http://build.invalid \
    SESSION_SECRET=build-time-placeholder-build-time-placeholder
RUN bun run build

# ---- runner -----------------------------------------------------------------
FROM node:20-slim AS runner
WORKDIR /app
ENV NODE_ENV=production \
    PORT=3000 \
    HOSTNAME=0.0.0.0

# Standalone output bundles the minimal server + traced node_modules.
COPY --from=builder /repo/apps/web-next/.next/standalone ./
COPY --from=builder /repo/apps/web-next/.next/static ./apps/web-next/.next/static
COPY --from=builder /repo/apps/web-next/public ./apps/web-next/public

EXPOSE 3000
# Standalone server entrypoint lives at the app's path inside the bundle.
CMD ["node", "apps/web-next/server.js"]
