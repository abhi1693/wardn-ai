FROM ghcr.io/astral-sh/uv:0.12.10@sha256:2bb3ebca0a796a155094a27773d290c4b074572e6107f171d88d086682fd2500 AS uv

FROM node:22-alpine3.24@sha256:c610fcdfb1d5b4740dd70c284ed3cb16bb857e0f7166196e36a5501df7a3aa32 AS node

FROM python:3.12-alpine3.24@sha256:b64631e04e4920160c50fbe8d8df828f7f35f06f425cb44aa09bca53e708a35a AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN apk upgrade --no-cache \
    && apk add --no-cache bash \
    && addgroup -S wardn \
    && adduser -S -D -G wardn -s /bin/bash wardn

COPY --from=uv /uv /uvx /bin/

ARG APP_VERSION=0.0.0
ENV APP_VERSION=$APP_VERSION \
    WARDN_APP_VERSION=$APP_VERSION \
    SETUPTOOLS_SCM_PRETEND_VERSION_FOR_WARDN_API=$APP_VERSION

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app ./app
COPY alembic.ini ./
RUN uv sync --frozen --no-dev --no-editable

LABEL org.opencontainers.image.version=$APP_VERSION

USER wardn

FROM base AS worker

USER root

COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm
RUN apk add --no-cache libstdc++ \
    && ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && npm install --global npm@12.0.2 \
    && npm pkg delete devDependencies workspaces --prefix /usr/local/lib/node_modules/npm --workspaces=false \
    && npm update --prefix /usr/local/lib/node_modules/npm --workspaces=false --omit=dev --ignore-scripts \
    && npm cache clean --force \
    && mkdir -p /var/lib/wardn/mcp-installations \
    && chown -R wardn:wardn /var/lib/wardn

ENV WARDN_MCP_INSTALL_ROOT=/var/lib/wardn/mcp-installations

VOLUME ["/var/lib/wardn/mcp-installations"]

USER wardn

CMD ["python", "-m", "app.manage", "runmcpjobs"]

FROM base AS runtime

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
