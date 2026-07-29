FROM ghcr.io/astral-sh/uv:0.11.21 AS uv
FROM denoland/deno:bin AS deno

FROM node:22-slim

ENV DENO_DIR=/tmp/deno \
    HOME=/tmp \
    NPM_CONFIG_CACHE=/tmp/npm-cache \
    UV_CACHE_DIR=/tmp/uv-cache \
    XDG_CACHE_HOME=/tmp/.cache \
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    CURL_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    PATH="/usr/local/bin:${PATH}"

COPY --from=uv /uv /uvx /usr/local/bin/
COPY --from=deno /deno /usr/local/bin/deno

RUN apt-get update \
    && apt-get install --no-install-recommends --yes ca-certificates \
    && update-ca-certificates \
    && npm install --global supergateway@3.4.3 \
    && npm cache clean --force

ENTRYPOINT ["supergateway"]
