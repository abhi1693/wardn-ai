FROM node:22-alpine3.24@sha256:c610fcdfb1d5b4740dd70c284ed3cb16bb857e0f7166196e36a5501df7a3aa32 AS deps
WORKDIR /app
COPY package.json package-lock.json ./
COPY wardn/frontend/package.json ./wardn/frontend/package.json
RUN npm ci --ignore-scripts

FROM node:22-alpine3.24@sha256:c610fcdfb1d5b4740dd70c284ed3cb16bb857e0f7166196e36a5501df7a3aa32 AS builder
WORKDIR /app
COPY --from=deps /app ./
COPY . .
RUN npm run web:build

FROM node:22-alpine3.24@sha256:c610fcdfb1d5b4740dd70c284ed3cb16bb857e0f7166196e36a5501df7a3aa32 AS runtime
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
