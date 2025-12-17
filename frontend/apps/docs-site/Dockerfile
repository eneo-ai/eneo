# Build stage using Bun
FROM oven/bun:1.3.0-slim AS builder

WORKDIR /app

# Copy workspace root files (context should be /workspace/frontend)
COPY bun.lock package.json ./
COPY apps/docs-site/package.json ./apps/docs-site/

# Install dependencies with Bun
RUN bun install --frozen-lockfile

# Copy application source
COPY apps/docs-site ./apps/docs-site

# Build the application
WORKDIR /app/apps/docs-site
RUN bun run build

# Production stage using Node.js (required for Next.js production server)
FROM node:20-alpine AS runner

WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

# Create non-root user
RUN addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 nextjs

# Copy built application (Next.js standalone output)
COPY --from=builder --chown=nextjs:nodejs /app/apps/docs-site/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/apps/docs-site/.next/static ./apps/docs-site/.next/static
COPY --from=builder --chown=nextjs:nodejs /app/apps/docs-site/public ./apps/docs-site/public

USER nextjs

EXPOSE 3000

ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

WORKDIR /app/apps/docs-site

CMD ["node", "server.js"]
