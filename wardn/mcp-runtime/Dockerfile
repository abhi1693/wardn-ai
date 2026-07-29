FROM ghcr.io/astral-sh/uv:0.11.21 AS uv
FROM denoland/deno:bin AS deno

FROM node:22-slim

ENV DENO_DIR=/tmp/deno \
    HOME=/tmp \
    NPM_CONFIG_CACHE=/tmp/npm-cache \
    UV_CACHE_DIR=/tmp/uv-cache \
    XDG_CACHE_HOME=/tmp/.cache \
    PATH="/usr/local/bin:${PATH}"

COPY --from=uv /uv /uvx /usr/local/bin/
COPY --from=deno /deno /usr/local/bin/deno

RUN npm install --global supergateway@3.4.3 \
    && npm cache clean --force

ENTRYPOINT ["supergateway"]
