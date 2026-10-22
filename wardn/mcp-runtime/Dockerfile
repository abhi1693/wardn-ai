FROM ghcr.io/astral-sh/uv:0.13.5@sha256:32a7bb39b496babbd997b0a39a4d66c126bdaf5661b302bf6f06abda8deca6ff AS uv
FROM node:26.12.1-alpine3.24@sha256:40cd011b55415bc894e45b02fdd5a5dfde056921b7d23a64c74f80497af48797 AS node
FROM python:3.13.17-alpine3.24@sha256:fa0bb0d0cd7c7d6cef30a69094d32ac2b71c7304c87c6107fec100e1ee4eda02 AS python

# The official Alpine Deno image includes its isolated glibc compatibility libraries.
FROM denoland/deno:alpine@sha256:75749604f68aea01d39bead15fd1c86343639e44eb8c58ab051da8a924799d01

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
COPY package.json package-lock.json /opt/wardn-runtime/

RUN apk upgrade --no-cache \
    && apk add --no-cache ca-certificates libatomic libstdc++ libffi xz-libs sqlite-libs libbz2 gdbm ncurses-libs readline \
    && update-ca-certificates \
    && ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && npm install --global npm@12.2.1 \
    && npm ci --prefix /opt/wardn-runtime --omit=dev --ignore-scripts \
    && ln -s /opt/wardn-runtime/node_modules/.bin/supergateway /usr/local/bin/supergateway \
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
