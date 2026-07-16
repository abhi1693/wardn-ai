FROM ghcr.io/astral-sh/uv:0.11.21 AS uv

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN useradd --create-home --shell /bin/bash wardn

COPY --from=uv /uv /uvx /bin/

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app ./app
COPY alembic.ini ./
RUN uv sync --frozen --no-dev --no-editable

ARG APP_VERSION=0.0.0
ENV APP_VERSION=$APP_VERSION
LABEL org.opencontainers.image.version=$APP_VERSION

USER wardn

FROM base AS worker

USER root

RUN apt-get update \
    && apt-get install --no-install-recommends --yes nodejs npm \
    && mkdir -p /var/lib/wardn/mcp-installations \
    && chown -R wardn:wardn /var/lib/wardn \
    && rm -rf /var/lib/apt/lists/*

ENV WARDN_MCP_INSTALL_ROOT=/var/lib/wardn/mcp-installations

VOLUME ["/var/lib/wardn/mcp-installations"]

USER wardn

CMD ["python", "-m", "app.manage", "runmcpjobs"]

FROM base AS runtime

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
