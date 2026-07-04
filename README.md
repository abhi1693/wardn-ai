# Wardn AI

Wardn AI is an enterprise MCP control plane and agent execution gateway. It lets
organizations connect MCP servers, expose them through a governed gateway, and
give agents safe access to tools with auditability, guardrails, scheduled work,
memory, and retrieval over workspace knowledge.

The product goal is not only to catalog MCP servers. Wardn should become the app
where teams decide which MCP servers are trusted, which agents can use them,
what policies apply before tools run, what scheduled tasks agents perform, and
how every tool call is traced back to a user, workspace, runtime, and policy
decision.

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
- Organization-scoped secret backend connections for external secret stores.
- LLM provider credentials and workspace agent chat with persisted
  conversations.
- Agent MCP server/tool binding, including entire-server binding.
- Kubernetes/k3s runtime support for package and OCI MCP servers.
- Agent run tracing foundation for chat turns and future scheduled tasks,
  guardrails, memory, and RAG.
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
        secrets/           External secret store integration
        llm_providers/     LLM credential and model access
        agents/            Agent, chat, conversation, and run tracing
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

1. Connect catalog sources such as Wardn Hub.
2. Add or sync verified MCP servers into the organization catalog.
3. Install MCP server configurations into a workspace.
4. Store required credentials in the configured secret backend.
5. Validate representative tool execution from the installed configuration.
6. Bind installed MCP servers or selected tools to workspace agents.
7. Chat with an agent or run a scheduled task through the governed MCP gateway.
8. Inspect agent runs, tool calls, runtime events, and future guardrail
   decisions from trace views.

Endpoint verification confirms that an MCP server initializes and exposes tools.
Tool validation confirms that the configured credentials can run a specific tool
with specific arguments.

## Product Roadmap

Wardn is organized around five product layers:

- MCP gateway and runtime: trusted catalog, installation, validation, runtime
  isolation, tool invocation, and traceability.
- Agents and conversations: workspace assistants that use bound MCP servers
  through Wardn rather than direct client-side tool access.
- Guardrails: policy checks before tool execution, including allow/deny rules,
  confirmation requirements, sensitive argument checks, and audit records.
- Scheduled tasks: recurring or one-off agent runs that use the same gateway,
  guardrails, traces, and secrets as chat.
- Knowledge and memory: workspace knowledge bases, agent memory, and RAG
  retrieval recorded as run steps.

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
