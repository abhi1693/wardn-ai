FROM node:22-slim AS deps
WORKDIR /app
COPY package.json package-lock.json ./
COPY wardn/frontend/package.json ./wardn/frontend/package.json
RUN npm ci --ignore-scripts

FROM node:22-slim AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY --from=deps /app/package.json /app/package-lock.json ./
COPY . .
RUN npm run web:build

FROM node:22-slim AS runtime
WORKDIR /app
ENV NODE_ENV=production

RUN useradd --create-home --shell /bin/bash wardn

COPY --from=builder /app/wardn/frontend/.next/standalone ./
COPY --from=builder /app/wardn/frontend/.next/static ./wardn/frontend/.next/static
COPY --from=builder /app/wardn/frontend/public ./wardn/frontend/public

ARG APP_VERSION=0.0.0
ENV APP_VERSION=$APP_VERSION
LABEL org.opencontainers.image.version=$APP_VERSION

USER wardn

EXPOSE 3000

CMD ["node", "wardn/frontend/server.js"]
