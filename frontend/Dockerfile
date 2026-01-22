# Helpdesk AI Frontend Dockerfile
# Multi-stage build for Next.js production using Bun

# Builder stage - single stage for deps + build
FROM oven/bun:1 AS builder
WORKDIR /app

# Copy package files first for better caching
COPY package.json bun.lockb* ./

# Install ALL dependencies (including devDependencies needed for build)
RUN bun install

# Copy source code
COPY . .

# Build arguments for environment variables
ARG NEXT_PUBLIC_API_URL
ARG NEXT_PUBLIC_APP_TITLE
ARG NEXT_PUBLIC_COMPANY_NAME

# Set environment variables for build
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL} \
    NEXT_PUBLIC_APP_TITLE=${NEXT_PUBLIC_APP_TITLE} \
    NEXT_PUBLIC_COMPANY_NAME=${NEXT_PUBLIC_COMPANY_NAME} \
    NEXT_TELEMETRY_DISABLED=1 \
    NODE_ENV=production

# Ensure public directory exists
RUN mkdir -p public

# Build the application
RUN bun run build

# Production stage - use node for running (more stable for Next.js)
FROM node:20-alpine AS runner
WORKDIR /app

# Set environment
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1

# Create non-root user
RUN addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 nextjs

# Copy public folder (create if doesn't exist)
COPY --from=builder /app/public ./public

# Copy standalone build
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

# Switch to non-root user
USER nextjs

# Expose port
EXPOSE 3000

ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

# Run the application
CMD ["node", "server.js"]
