FROM ghcr.io/astral-sh/uv:0.12.10@sha256:2bb3ebca0a796a155094a27773d290c4b074572e6107f171d88d086682fd2500 AS uv
FROM node:22-alpine3.24@sha256:c610fcdfb1d5b4740dd70c284ed3cb16bb857e0f7166196e36a5501df7a3aa32 AS node
FROM python:3.13-alpine3.24@sha256:7415fbc3c9e4979cc717d92377ab2bc7b2b4a2af1ac03cc52b5f3f88efedaf3a AS python

# The official Alpine Deno image includes its isolated glibc compatibility libraries.
FROM denoland/deno:alpine@sha256:aa665f8777136863b5b8a0445a5cdfccff8103b5f40c9a877de5276b04facb1e

ENV DENO_DIR=/tmp/deno \
    HOME=/tmp \
    NPM_CONFIG_CACHE=/tmp/npm-cache \
    UV_CACHE_DIR=/tmp/uv-cache \
    UV_PYTHON_DOWNLOADS=never \
    XDG_CACHE_HOME=/tmp/.cache \
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    CURL_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    PATH="/usr/local/bin:${PATH}"

COPY --from=python /usr/local/ /usr/local/
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm
COPY --from=uv /uv /uvx /usr/local/bin/
COPY structured-content-proxy.mjs /opt/wardn-runtime/structured-content-proxy.mjs

RUN apk upgrade --no-cache \
    && apk add --no-cache ca-certificates libstdc++ libffi xz-libs sqlite-libs libbz2 gdbm ncurses-libs readline \
    && update-ca-certificates \
    && ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && npm install --global npm@12.0.2 supergateway@3.4.3 \
    && npm pkg delete devDependencies workspaces --prefix /usr/local/lib/node_modules/npm --workspaces=false \
    && npm update --prefix /usr/local/lib/node_modules/npm --workspaces=false --omit=dev --ignore-scripts \
    && npm cache clean --force \
    && python3 -m pip uninstall --yes pip \
    && rm -rf /usr/local/lib/python3.13/ensurepip \
    && python3 --version \
    && uv python find 3.13 \
    && node --version \
    && deno --version

ENTRYPOINT ["supergateway"]
