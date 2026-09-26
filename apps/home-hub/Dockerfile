FROM node:22-bookworm-slim AS deps

WORKDIR /srv/home-hub
COPY --chown=node:node package.json package-lock.json ./
USER node
RUN npm ci --include=dev

FROM deps AS builder
ARG HOME_HUB_BFF_BASE_URL=http://127.0.0.1:9933
ARG HOME_HUB_PUBLIC_ORIGIN=https://bff.home.episteck.com
ENV NODE_ENV=production \
    HOME_HUB_DATA_MODE=LIVE \
    HOME_HUB_BFF_BASE_URL=${HOME_HUB_BFF_BASE_URL} \
    HOME_HUB_PUBLIC_ORIGIN=${HOME_HUB_PUBLIC_ORIGIN} \
    NEXT_TELEMETRY_DISABLED=1

COPY --chown=node:node . .
RUN npm run build

FROM node:22-bookworm-slim AS runner
ENV NODE_ENV=production \
    HOME_HUB_DATA_MODE=LIVE \
    NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=0.0.0.0 \
    PORT=3000

WORKDIR /srv/home-hub
COPY --from=builder --chown=node:node /srv/home-hub/public ./public
COPY --from=builder --chown=node:node /srv/home-hub/.next/standalone ./
COPY --from=builder --chown=node:node /srv/home-hub/.next/static ./.next/static

USER node
EXPOSE 3000
CMD ["node", "server.js"]
