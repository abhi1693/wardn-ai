FROM node:22-slim AS deps
WORKDIR /app
COPY package*.json ./
RUN npm install

FROM node:22-slim AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:22-slim AS runtime
WORKDIR /app
ENV NODE_ENV=production

RUN useradd --create-home --shell /bin/bash wardn

COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public

USER wardn

EXPOSE 3000

CMD ["node", "server.js"]
