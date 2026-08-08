# Wardn AI

Wardn AI is a control plane for governed AI tool access.

It gives teams one place to approve Model Context Protocol (MCP) servers, connect
secrets and model providers, run assistants, and review every tool call, approval,
cost, and runtime issue. Agents can still use the MCP ecosystem, but the decisions
about trust, credentials, policy, and auditability stay in Wardn instead of being
spread across local config files and one-off bots.

[Product Areas](#product-areas) | [Typical Workflow](#typical-workflow) |
[Local Development](#local-development) | [Production Notes](#production-notes)

## Documentation

Wardn's public documentation source lives in `docs/`. It uses Antora and AsciiDoc
to build a static, versioned docs site.

```bash
cd docs
npm ci
npm run build
npm run preview
```

The root package also exposes `npm run docs:build`, `npm run docs:preview`, and
`npm run docs:sync:openapi`.

## What Wardn Is For

AI agents become useful when they can act across company systems: source control,
tickets, documents, data stores, customer tools, and internal APIs. The hard part is
not only connecting those tools. Teams also need to know which tools are approved,
who can use them, which credentials are in play, when a human must approve an action,
and what happened after an agent ran.

Wardn is built for that operating layer:

- Curate a trusted catalog of MCP servers for each organization.
- Install and validate tool servers inside scoped workspaces.
- Bind approved tools to agents instead of exposing broad credentials directly.
- Apply access rules, limits, and human approvals before risky work runs.
- Run agents through chat, scheduled tasks, and connected chat channels.
- Trace LLM usage, tool calls, runtime sessions, errors, and approvals from one UI.

## Product Areas

### Trusted MCP Catalog

Wardn gives platform teams a governed registry for MCP servers and versions. Teams
can add, review, edit, and sync server metadata, then install approved servers into
the workspaces that need them.

### Workspace Agents

Workspace agents use configured LLM providers and the MCP servers assigned to them.
They can work in interactive conversations, reusable skills, and scheduled tasks
while keeping tool access inside Wardn's policy and audit path.

### Guardrails and Approvals

Access rules can require approval, restrict tool use, and route decisions to the
right reviewer. Approval records are tied to the exact stored tool call and
arguments, so approval is scoped to the action being reviewed.

### Scheduled Work

Wardn can run recurring or one-off agent tasks using the same tools, approvals,
chat history policy, output routes, and run tracing as interactive chat.

### Observability and Usage

Dashboards show organization and workspace health, installed servers, runtime
sessions, tool failures, LLM usage, model pricing, and agent runs that need
attention. The goal is to make AI automation operable, not opaque.

### Enterprise Controls

Wardn supports organization and workspace boundaries, local or OIDC authentication,
API tokens, usage limits, managed secrets, operator-managed OpenBao profiles, and
chat provider connections including Slack, Telegram, and WhatsApp.

## Typical Workflow

1. Create an organization and one or more workspaces.
2. Curate the MCP catalog or sync metadata from trusted sources.
3. Install MCP servers into a workspace and validate their tools.
4. Store credentials in the configured secret backend.
5. Create agents and bind the servers or individual tools they are allowed to use.
6. Add access rules, limits, and approval routes for sensitive actions.
7. Run agents through chat, scheduled tasks, or connected chat providers.
8. Review traces, tool calls, approvals, failures, and usage from the dashboards.

Endpoint validation proves that a server initializes and exposes tools. Tool
validation proves that the configured credentials can run a specific tool with
specific arguments.

## How It Is Built

Wardn is a monorepo with a FastAPI backend, a Next.js application, PostgreSQL
persistence, and dedicated worker processes for background operations. The runtime
layer supports local development and Kubernetes-oriented execution for MCP servers
that need stronger isolation.

```text
wardn/
  backend/        FastAPI API, domain services, SQLAlchemy models, Alembic migrations
  frontend/       Next.js app, UI components, generated API client
  mcp-runtime/    Runtime support for MCP server execution
  whatsapp-bridge/ Optional local bridge for WhatsApp provider pairing
```

Core backend modules are organized by product domain, including users,
organizations, MCP registry, MCP gateway, MCP runtime, secrets, LLM providers,
agents, guardrails, limits, scheduled tasks, chat providers, and observability.

## Local Development

### Prerequisites

- Python 3.12
- Node.js and npm
- PostgreSQL
- `uv`
- Package runtimes required by the MCP servers you install
- Kubernetes or k3s only when testing Kubernetes-backed runtime execution

### Backend

Create a local environment file:

```bash
cp wardn/backend/.env.example wardn/backend/.env
```

Install backend dependencies, apply migrations, and run the API:

```bash
cd wardn/backend
uv sync --extra dev
uv run alembic upgrade head
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Run the MCP job worker in a separate terminal during local development:

```bash
cd wardn/backend
uv run python -m app.manage runmcpjobs
```

Useful backend endpoints:

- `GET /api/v1/health/live`
- `GET /api/v1/health/ready`
- `GET /api/v1/openapi.json`
- `POST /api/v1/mcp/gateway`

### Frontend

Install frontend dependencies and start the web app:

```bash
npm install
npm run web:dev
```

For local development with the UI and API on separate ports, set:

```bash
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
```

Also include the frontend origin in `WARDN_CORS_ORIGINS`.

## Production Notes

Run the API, web app, MCP job worker, scheduled task worker, chat provider event
worker, and secret cleanup worker as separate workloads. The API does not start the
MCP job worker in-process.

In production, route `/api/v1`, `/api/v1/oauth`, and `/.well-known` to the backend
at the ingress so the UI and API share an origin. This keeps session cookies
available to browser and server-rendered requests without an application-level
proxy. If the browser must call a different API or WebSocket origin, list those
origins in `WARDN_CSP_CONNECT_SRC`.

For containerized MCP work, set `WARDN_MCP_JOB_WORKER_ISOLATION=container` and run
the worker with a dedicated service identity, explicit CPU and memory limits, a
read-only root filesystem, and only the installation volume writable. Limit egress
to approved package, catalog, secret-store, and database destinations.

OpenBao credentials are configured by operators, not organization administrators.
Set `WARDN_OPENBAO_AUTH_FILE_ROOT` to a read-only credential mount and define named
profiles with `WARDN_OPENBAO_AUTH_PROFILES_JSON`. Secret-store API callers select a
profile; they cannot configure credential paths, authentication methods,
namespaces, or TLS behavior.

Outbound OpenBao, catalog-sync, and remote MCP requests use a shared SSRF policy.
Public HTTPS on port `443` is allowed by default. Internal destinations,
nonstandard ports, and plain HTTP require explicit operator configuration.

## Common Commands

| Task | Command |
| --- | --- |
| Backend lint | `npm run backend:lint` |
| Backend tests | `npm run backend:test` |
| Backend typecheck | `npm run backend:typecheck` |
| Generate API client | `npm run web:api:generate` |
| Frontend lint | `npm run web:lint` |
| Frontend build | `npm run web:build` |
| Frontend end-to-end tests | `npm run web:e2e` |

Regenerate the OpenAPI schema and Orval client whenever backend request or response
schemas change:

```bash
npm run web:api:generate
```

This updates:

- `wardn/frontend/openapi/wardn-api.json`
- `wardn/frontend/lib/api/generated/`

## Configuration

Runtime settings use the `WARDN_` prefix. Start with
`wardn/backend/.env.example`, then configure at least the database URL, session
secret, CORS origins, frontend base URL, authentication mode, secret backend
profiles, worker settings, and runtime provider for your environment.

Do not commit credentials, service tokens, `.env` files with real secrets, local
database dumps, or private research notes. MCP credentials should be treated as
secrets even when used only for validation.

## Contributing

Keep backend modules domain-oriented and frontend pages focused on complete product
workflows. Include focused tests for service behavior, OpenAPI contracts, and
gateway error paths. When API schemas change, commit the regenerated OpenAPI and
Orval artifacts with the backend change.
