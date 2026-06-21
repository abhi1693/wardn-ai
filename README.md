# Wardn AI

Wardn AI is an enterprise-focused platform for managing Model Context Protocol
(MCP) servers behind a unified registry and gateway. The current implementation
focuses on a backend-first foundation: local user authentication, a verified MCP
server catalog, installable server configurations, runtime validation, and a
gateway that lets agents discover and call enabled MCP tools through one entry
point.

Future product areas such as guardrails, unified chat, and RAG are intentionally
deferred until the MCP gateway and registry foundation are stable.

## Current Capabilities

- Local database-backed user authentication.
- Django-style backend management commands, including superuser creation.
- PostgreSQL persistence with SQLAlchemy and Alembic migrations.
- Verified MCP server registry with create, edit, delete, and version support.
- MCP server installation/configuration flow for remote endpoints and package
  runtimes.
- MCP gateway tools for searching enabled servers, discovering tools, and
  invoking selected MCP tools.
- Installed-server tool validation to distinguish endpoint discovery from
  credential-level tool execution.
- Next.js frontend using shadcn-style UI primitives and generated API types.

## Repository Layout

```text
wardn/
  backend/                 FastAPI backend service
    app/
      api/                 API router composition
      commands/            Management command registry
      core/                Settings, logging, shared configuration
      db/                  SQLAlchemy session and Alembic migrations
      modules/
        users/             Local identity and user management
        mcp_registry/      MCP catalog, install metadata, registry APIs
        mcp_gateway/       Unified MCP gateway JSON-RPC endpoint
        mcp_runtime/       Runtime sessions and tool invocation tracking
      openapi.py           OpenAPI export command
    tests/                 Pytest suite
  frontend/                Monolithic Next.js application
    app/                   App Router pages and API proxy routes
    components/ui/         Shared UI primitives
    lib/api/generated/     Orval-generated API client types
    openapi/               Exported backend OpenAPI schema
docs/                      Local project notes and research
```

## Prerequisites

- Python 3.12
- Node.js and npm
- PostgreSQL
- `uv`, `npm`, or other package runtimes as required by configured MCP servers
- A reachable Kubernetes environment for future runtime deployments

## Backend Setup

Create or update `wardn/backend/.env` from the example:

```bash
cp wardn/backend/.env.example wardn/backend/.env
```

Install backend dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
cd wardn/backend
pip install -e ".[dev]"
```

Apply database migrations:

```bash
cd wardn/backend
../../.venv/bin/alembic upgrade head
```

Run the backend:

```bash
cd wardn/backend
../../.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Useful endpoints:

- `GET /api/v1/health/live`
- `GET /api/v1/health/ready`
- `GET /api/v1/openapi.json`
- `POST /api/v1/mcp/gateway`

## Frontend Setup

Install frontend dependencies:

```bash
npm install
```

Run the frontend:

```bash
npm run web:dev
```

Build and lint:

```bash
npm run web:build
npm run web:lint
```

The frontend expects the backend at `http://127.0.0.1:8000` by default. Override
with `WARDN_BACKEND_URL` when needed.

## Management Commands

Create the first superuser:

```bash
cd wardn/backend
../../.venv/bin/python -m app.manage createsuperuser
```

MCP registry commands are also exposed through the same modular command system.
Use `python -m app.manage --help` to inspect available commands.

## API Client Generation

The frontend API model is generated from FastAPI OpenAPI via Orval. Regenerate it
whenever backend request/response schemas change:

```bash
cd wardn/backend
../../.venv/bin/python -m app.openapi --output ../frontend/openapi/wardn-api.json

cd ../frontend
npm run api:generate
```

This updates:

- `wardn/frontend/openapi/wardn-api.json`
- `wardn/frontend/lib/api/generated/`

## Testing

Run backend tests:

```bash
cd wardn/backend
../../.venv/bin/pytest
```

Run focused suites during MCP gateway work:

```bash
../../.venv/bin/pytest tests/test_mcp_gateway.py tests/test_mcp_runtime_service.py
../../.venv/bin/pytest tests/test_mcp_registry_service.py tests/test_openapi.py
```

Run frontend validation:

```bash
npm run web:lint
npm run web:build
```

## MCP Workflow

1. Add or edit a verified MCP server in the registry.
2. Define runtime targets, environment variables, headers, and package
   arguments in the server metadata.
3. Install a server configuration from the Install page.
4. Validate representative tool execution from the installed configuration.
5. Use the unified MCP gateway to search enabled servers, inspect tool schemas,
   and invoke selected tools.

Endpoint verification confirms that an MCP server initializes and exposes tools.
Tool validation confirms that the configured credentials can run a specific tool
with specific arguments.

## Configuration and Secrets

Runtime settings use the `WARDN_` prefix. Common local values include:

- `WARDN_DATABASE_URL`
- `WARDN_CORS_ORIGINS`
- `WARDN_SESSION_SECRET`
- `WARDN_MCP_INSTALL_ROOT`
- `WARDN_MCP_RUNTIME_PROVIDER`

Do not commit credentials, service tokens, `.env` files with real secrets, local
database dumps, or private research notes. MCP credentials should be treated as
secrets even when used only for validation.

## Contributing

Keep backend modules domain-oriented and frontend pages focused on real product
workflows. Include tests for service behavior, OpenAPI contracts, and gateway
error paths. When API schemas change, commit the regenerated OpenAPI and Orval
artifacts with the backend change.
