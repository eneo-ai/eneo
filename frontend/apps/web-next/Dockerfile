# Eneo web-next production image.
# Install deps with Bun (honours the committed bun.lock) but build and run on
# Node 20: Next 16's native modules don't load under the Bun runtime, so
# `next build` must run under Node. Output is Next's standalone bundle
# (next.config.ts sets output: "standalone").
#
#   docker build -f frontend/apps/web-next/Dockerfile -t eneo-web-next ./frontend
#
# The build context is ./frontend so the bun workspace (packages/*) resolves.

# ---- deps + build -----------------------------------------------------------
# Node base for the build (Next runs under Node), with the pinned bun binary
# copied in for install. The version is pinned because a floating `oven/bun:1`
# drifts ahead of the committed bun.lock (generated with bun@1.3.x, see root
# package.json "packageManager") and breaks `bun install --frozen-lockfile`.
FROM node:20-slim AS builder
COPY --from=oven/bun:1.3.4 /usr/local/bin/bun /usr/local/bin/bun
WORKDIR /repo

# Workspace manifests first for a cached install layer. Bun validates the
# entire workspace under --frozen-lockfile, so every member's manifest must be
# present (apps/* + packages/*) even though we only build web-next.
COPY package.json bun.lock ./
COPY apps/web-next/package.json apps/web-next/package.json
COPY apps/web/package.json apps/web/package.json
COPY apps/docs-site/package.json apps/docs-site/package.json
COPY packages ./packages
# --ignore-scripts: skip workspace prepare hooks (e.g. apps/web's `svelte-kit
# sync`) whose source isn't copied here. web-next has no workspace deps and
# Next's native binaries ship as optional deps, not postinstall scripts.
RUN bun install --frozen-lockfile --ignore-scripts

# App source.
COPY apps/web-next ./apps/web-next
WORKDIR /repo/apps/web-next

# A throwaway env so env.ts (zod-validated at import during page-data
# collection) passes the build; real values are injected at runtime.
ENV ENEO_BACKEND_URL=http://build.invalid \
    SESSION_SECRET=build-time-placeholder-build-time-placeholder
# Run via npm (not `bun run`) so the next CLI executes under Node, not Bun.
RUN npm run build

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
