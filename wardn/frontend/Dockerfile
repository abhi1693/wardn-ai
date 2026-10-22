FROM node:26.12.1-alpine3.24@sha256:40cd011b55415bc894e45b02fdd5a5dfde056921b7d23a64c74f80497af48797 AS deps
WORKDIR /app
COPY package.json package-lock.json ./
COPY packages/braces ./packages/braces
COPY wardn/frontend/package.json ./wardn/frontend/package.json
RUN npm ci --ignore-scripts

FROM node:26.12.1-alpine3.24@sha256:40cd011b55415bc894e45b02fdd5a5dfde056921b7d23a64c74f80497af48797 AS builder
WORKDIR /app
COPY --from=deps /app ./
COPY . .
RUN npm run web:build

FROM node:26.12.1-alpine3.24@sha256:40cd011b55415bc894e45b02fdd5a5dfde056921b7d23a64c74f80497af48797 AS runtime
WORKDIR /app
ENV NODE_ENV=production

COPY --from=builder /app/wardn/frontend/.next/standalone ./
COPY --from=builder /app/wardn/frontend/.next/static ./wardn/frontend/.next/static
COPY --from=builder /app/wardn/frontend/public ./wardn/frontend/public

RUN apk upgrade --no-cache \
    && rm -rf /usr/local/lib/node_modules/npm /opt/yarn-* \
    && rm -f /usr/local/bin/npm /usr/local/bin/npx /usr/local/bin/yarn /usr/local/bin/yarnpkg \
    && mkdir -p /app/wardn/frontend/.next/cache \
    && chown -R node:node /app/wardn/frontend/.next/cache

ARG APP_VERSION=0.0.0
ENV APP_VERSION=$APP_VERSION
LABEL org.opencontainers.image.version=$APP_VERSION

USER node

EXPOSE 3000

CMD ["node", "wardn/frontend/server.js"]
