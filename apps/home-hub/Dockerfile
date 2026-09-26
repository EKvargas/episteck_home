FROM node:22-bookworm-slim

ENV NODE_ENV=production \
    HOME_HUB_DATA_MODE=LIVE \
    NEXT_TELEMETRY_DISABLED=1

WORKDIR /srv/home-hub
COPY --chown=node:node package.json package-lock.json ./
USER node
RUN npm ci

COPY --chown=node:node . .
RUN npm run build

EXPOSE 3000
CMD ["npm", "run", "start", "--", "--hostname", "0.0.0.0", "--port", "3000"]
