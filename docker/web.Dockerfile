# Next.js front end from web/, served by the standalone server on 3000.
# Needs `output: "standalone"` in web/next.config. Build context: repo root.
FROM node:22-alpine AS deps
WORKDIR /app
COPY web/package.json web/package-lock.json* web/pnpm-lock.yaml* web/yarn.lock* ./
RUN corepack enable \
    && if [ -f pnpm-lock.yaml ]; then pnpm install --frozen-lockfile; \
       elif [ -f yarn.lock ]; then yarn install --frozen-lockfile; \
       elif [ -f package-lock.json ]; then npm ci; \
       else npm install; fi

FROM node:22-alpine AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
# Public (browser) config is baked at build time; azd passes it from the env.
ARG NEXT_PUBLIC_TALKBACK_API_URL=""
ENV NEXT_PUBLIC_TALKBACK_API_URL=$NEXT_PUBLIC_TALKBACK_API_URL
COPY --from=deps /app/node_modules ./node_modules
COPY web/ ./
RUN mkdir -p public \
    && if [ -f pnpm-lock.yaml ]; then corepack enable && pnpm run build; \
       elif [ -f yarn.lock ]; then corepack enable && yarn build; \
       else npm run build; fi

FROM node:22-alpine AS run
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0
RUN addgroup -S -g 1001 nodejs && adduser -S -u 1001 -G nodejs nextjs
COPY --from=build --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=build --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=build --chown=nextjs:nodejs /app/public ./public
USER nextjs
EXPOSE 3000
CMD ["node", "server.js"]
