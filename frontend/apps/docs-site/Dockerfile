# Build stage
FROM node:20-alpine AS builder

# Install pnpm
RUN corepack enable && corepack prepare pnpm@9.12.3 --activate

WORKDIR /app

# Copy workspace root files (context should be /workspace/frontend)
COPY pnpm-lock.yaml pnpm-workspace.yaml package.json ./
COPY apps/docs-site/package.json ./apps/docs-site/

# Install dependencies for the entire workspace
RUN pnpm install --frozen-lockfile --filter docs-site...

# Copy application source
COPY apps/docs-site ./apps/docs-site

# Build the application
WORKDIR /app/apps/docs-site
RUN pnpm build

# Production stage
FROM node:20-alpine AS runner

# Install pnpm
RUN corepack enable && corepack prepare pnpm@9.12.3 --activate

WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

# Create non-root user
RUN addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 nextjs

# Copy package files for production dependencies
COPY --from=builder /app/package.json /app/pnpm-lock.yaml /app/pnpm-workspace.yaml ./
COPY --from=builder /app/apps/docs-site/package.json ./apps/docs-site/

# Install production dependencies only
RUN pnpm install --frozen-lockfile --filter docs-site... --prod

# Copy built application
COPY --from=builder --chown=nextjs:nodejs /app/apps/docs-site/.next ./apps/docs-site/.next
COPY --from=builder --chown=nextjs:nodejs /app/apps/docs-site/public ./apps/docs-site/public
COPY --from=builder --chown=nextjs:nodejs /app/apps/docs-site/next.config.ts ./apps/docs-site/

USER nextjs

EXPOSE 3000

ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

WORKDIR /app/apps/docs-site

CMD ["pnpm", "start"]