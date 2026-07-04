# Wardn AI Backend-First Architecture Research

Date: 2026-06-21
Repository: https://github.com/abhi1693/wardn-ai
Status: initial research baseline for the first implementation commit

## Product Direction

Wardn AI should become the enterprise gateway for MCP servers and the agents
that use them. The product is a governed execution control plane: teams connect
MCP servers, bind them to agents, enforce policies before tools run, schedule
agent work, and inspect every run through audit and trace data.

The registry and runtime foundation remain critical, but they are not the final
product. They support the higher-level Wardn loop:

```text
MCP catalog and runtime
  -> governed MCP gateway
  -> agents with server/tool bindings
  -> guardrails and run traces
  -> scheduled agent tasks
  -> knowledge, memory, and RAG retrieval
```

The engineering priority is still backend correctness, but guardrails,
scheduled tasks, and RAG must be treated as first-class platform layers rather
than vague future ideas. Each of them should reuse the same agent run trace and
MCP invocation path.

## Baseline Stack

- Backend: FastAPI, Python 3.12, Pydantic v2, pydantic-settings.
- Database: PostgreSQL, SQLAlchemy 2.x ORM, Alembic migrations.
- Auth: local database users first, with provider boundaries for OAuth/OIDC/SAML later.
- Frontend: Next.js App Router, TypeScript.
- Packaging: Docker images for API and web, Helm chart for k3s deployment.
- Observability: structured JSON logs from day 0; OpenTelemetry hooks before multi-service scale.

## Architectural Style

Start as a modular monolith, not microservices.

Reasons:

- The domain boundaries are still forming.
- A single FastAPI service is easier to deploy and test in k3s.
- SQL transactions remain simple for auth, workspace ownership, MCP config, and invocation audit records.
- Clean module boundaries let us split workers or services later without rewriting the whole app.

The backend should use vertical feature modules plus shared infrastructure:

```text
apps/api/
  app/
    main.py
    core/
      config.py
      logging.py
      security.py
      errors.py
    db/
      base.py
      session.py
      migrations/
    modules/
      auth/
      users/
      workspaces/
      mcp_servers/
      audit/
    integrations/
      mcp/
    workers/
```

Each module should own its API router, SQLAlchemy models, Pydantic schemas, service layer, and repository/data-access code. Shared code belongs in `core`, `db`, or `integrations` only when at least two modules need it.

## Initial MVP Scope

### In Scope

- Local user auth.
- Workspace ownership so MCP server config is scoped from day 0.
- Internal MCP registry/catalog for installable servers.
- Registry import/sync from the official MCP Registry.
- MCP server installation/configuration from registry entries.
- MCP capability discovery and sync.
- MCP invocation gateway.
- Invocation/audit records.
- Basic health/config/deployment foundation for k3s.
- Minimal Next.js admin shell after backend contracts exist.

### Later MVP Slices

The initial gateway foundation should be followed by these product slices:

- Agent chat with persisted conversations and MCP server/tool binding.
- Agent run tracing that records model input/output, tool calls, tool results,
  errors, and future policy decisions.
- Guardrails at the MCP invocation boundary, not only in the frontend.
- Scheduled agent tasks that reuse the same agent execution path as chat.
- Knowledge base, memory, and RAG retrieval recorded as agent run steps.
- Multi-tenant billing, SSO, SCIM, and advanced RBAC after the execution loop is
  trustworthy.

## Initial Domain Modules

### Auth

Local DB auth should be implemented behind an interface so the gateway can later support OIDC/SAML/API keys without changing endpoint-level dependencies.

Initial responsibilities:

- Register/login users.
- Store password hashes only.
- Issue short-lived access tokens.
- Provide dependency helpers such as `current_user`.
- Record auth events for audit.

Future provider boundary:

- `AuthProvider` interface: local, OIDC, SAML, API key, service account.
- `IdentityLink` table to map external identities to local users.
- Token issuance stays internal even when login is delegated.

### Workspaces

Add a workspace table early, even if the first UI has one workspace per user. MCP server definitions, capability snapshots, and invocation logs should belong to a workspace from the start.

### MCP Servers

This is the primary MVP domain.

Initial model concepts:

- Registry server: canonical installable server metadata, based on the MCP Registry `server.json` shape.
- Registry server version: versioned package/remote metadata and registry-managed status.
- Installed server: workspace-specific server installation selected from registry metadata, with resolved config/secrets and enabled flag.
- Capability snapshot: tools, resources, prompts, schema metadata, last sync status.
- Invocation record: request metadata, user/workspace, status, latency, error summary.

Recommended first transport:

- Support importing both `remotes` and `packages` into the registry catalog.
- Make remote Streamable HTTP the first directly runnable installation type because it is k3s-friendly.
- Store STDIO/package-based registry entries from day 0, but gate actual installation until a runner strategy exists.
- Prefer OCI/package installation next because it can be isolated as Kubernetes Jobs/Deployments more safely than arbitrary host STDIO.

Initial API behavior:

- Browse/search registry entries.
- Import a registry entry from `server.json` or official registry API data.
- Install a registry server version into a workspace.
- Configure required headers/environment variables using the registry's input metadata.
- Validate installed server connection.
- Sync and persist installed server capabilities.
- List tools/resources/prompts from the persisted snapshot.
- Invoke a tool through the gateway.
- Record invocation inputs/outputs safely, with redaction hooks even if redaction is initially basic.

### Registry Compatibility

The official MCP Registry should influence Wardn's metadata model and API shape. Wardn should implement an internal registry/catalog as part of the app, then use that registry as the source of installable MCP servers.

Important distinction:

- MCP Registry: public metadata catalog, like an app store. It hosts server metadata, not runtime execution state.
- Wardn MCP Registry: private/local catalog of MCP servers that can be installed into workspaces. It can sync from the official registry and accept custom/private entries.
- Wardn MCP Gateway: private operational control plane. It manages installed MCP connections, secrets, capability snapshots, invocation routing, and audit trails.

MVP implications:

- Store registry metadata using the `server.json` shape where possible.
- Support official registry names such as `io.github.user/server-name`.
- Preserve `packages`, `remotes`, `repository`, `websiteUrl`, `_meta`, and registry-managed status metadata when importing.
- Prefer `remotes[].type == "streamable-http"` for first-class installable/runnable connections.
- Treat `packages[].transport.type == "stdio"` as catalog/install metadata until runner isolation is explicitly implemented.
- Use the registry's `isSecret` hints for headers/environment variables to drive secret handling in our config UI and persistence.
- Keep Wardn-owned runtime state separate from registry metadata: installed workspace, enabled/disabled, resolved secrets, last sync, capability snapshots, and invocation logs.
- Add official registry sync/import that reads `GET /v0.1/servers`, `GET /v0.1/servers/{serverName}/versions`, and `GET /v0.1/servers/{serverName}/versions/latest`.

MVP registry API should be internal/admin-focused first, but its read shape can stay close to the official registry API:

```text
/api/v1/registry/servers
/api/v1/registry/servers/{server_name}/versions
/api/v1/registry/servers/{server_name}/versions/{version}
/api/v1/registry/import
/api/v1/registry/sync/official
/api/v1/workspaces/{workspace_id}/installed-servers
/api/v1/workspaces/{workspace_id}/installed-servers/{installed_server_id}
/api/v1/workspaces/{workspace_id}/installed-servers/{installed_server_id}/sync
/api/v1/workspaces/{workspace_id}/installed-servers/{installed_server_id}/tools/{tool_name}/invoke
```

Do not build public publishing, namespace ownership verification, package ownership verification, or public subregistry behavior in the first MVP. Private/custom registry entries can be added by authenticated admins without namespace proof.

### Guardrails

Guardrails are a core Wardn feature. They should run at the backend MCP
invocation boundary so chat, scheduled tasks, and future API-triggered agents
all share the same enforcement point.

Initial guardrail scope:

- tool allow/deny rules by workspace, agent, server, and tool,
- confirmation requirements for destructive or sensitive tools,
- argument inspection with secret redaction before trace display,
- policy decision records linked to agent runs and MCP invocations.

### Audit

Audit is in scope only for gateway events:

- MCP server created/updated/deleted.
- Capability sync started/succeeded/failed.
- Tool/resource/prompt invocation started/succeeded/failed.
- Auth login/logout/token refresh.

### Chat, Scheduled Tasks, Memory, And RAG

Chat is the first interactive agent surface, but scheduled tasks should use the
same execution path and produce the same traces. RAG and memory should not be
separate side systems; retrieval must appear as explicit run steps so users can
see which knowledge influenced a model response or tool choice.

RAG can start with PostgreSQL-backed document/chunk storage and full-text search.
Add pgvector only when semantic retrieval quality requires it.

## Database Direction

Use SQLAlchemy 2.x typed declarative mappings:

- UUID primary keys.
- `created_at` and `updated_at` timestamps on owned tables.
- Explicit foreign keys and indexes in migrations.
- Avoid ORM magic in business logic; use service methods and repositories.

MVP tables:

- `users`
- `workspaces`
- `registry_sources`
- `registry_servers`
- `registry_server_versions`
- `installed_mcp_servers`
- `mcp_capability_snapshots`
- `mcp_invocations`
- `audit_events`

For registry tables, keep a compact relational surface plus JSON metadata:

- `registry_name`
- `title`
- `description`
- `version`
- `source_type`: manual, official_registry, custom_registry
- `source_url`
- `status`: active, deprecated, deleted
- `is_latest`
- `server_json`
- `registry_response_metadata_json`

For installed servers, store workspace runtime state:

- `workspace_id`
- `registry_server_version_id`
- `transport_type`
- `transport_url`
- `runtime_config_json`
- `secret_refs_json`
- `enabled`
- `install_status`: pending_config, installed, disabled, failed
- `last_validated_at`
- `last_sync_at`

Alembic should be configured on day 0:

- First migration creates the MVP core tables.
- Use migration-generated schema, not `metadata.create_all`, outside tests.
- Do not enable `vector` until RAG is actually in scope.

## Archestra Reference Findings

Archestra is useful as a reference architecture, even though its stack is Fastify/TypeScript/Drizzle rather than FastAPI/SQLAlchemy. The important lesson is its domain split, not its implementation language.

Core split:

- Catalog entry: installable MCP server template and metadata.
- Installed server: user/team/org-specific runtime instance created from a catalog entry.
- Tools: discovered capabilities exposed by an MCP server.
- Tool calls: persisted invocation log for audit/debugging.

Archestra's catalog model keeps registry/template data separate from runtime installation state. Catalog fields include `name`, `version`, `description`, `instructions`, `repository`, `installationCommand`, auth metadata, `serverType`, `serverUrl`, local config, user config, OAuth config, Kubernetes deployment YAML, ownership scope, and reinstall flags.

Archestra's installed server model keeps operational state: `catalogId`, `serverType`, secret references, non-secret environment values, owner/team/scope, reinstall flag, local installation status, local installation error, and OAuth refresh failure metadata.

Archestra's config model is a strong template for Wardn:

- Local config supports command/arguments/environment, Docker image, `stdio` or `streamable-http`, HTTP port/path, node port, service account, image pull secrets.
- Environment variables are typed as plain text, secret, boolean, or number.
- User config fields support required/prompted values, sensitive values, headers, defaults, min/max, and multi-value fields.
- Sensitive header defaults are forbidden, which is a good validation rule to copy.

Install flow pattern:

1. Fetch catalog entry first. The catalog is the source of install metadata.
2. Validate scope/authorization.
3. Prevent duplicates. Personal duplicates can be idempotent; team/org duplicates should error.
4. Resolve prompted config values and secret values.
5. For remote servers, validate connection and fetch tools synchronously.
6. For local servers, create DB row, create Kubernetes runtime, move status through pending/discovering/success/error asynchronously.
7. Persist discovered tools and make them available through the gateway.

Gateway pattern:

- Expose an MCP-compatible endpoint to downstream clients, not only REST admin endpoints.
- Use bearer tokens and explicit auth challenge metadata.
- Create request-scoped transports/server instances where practical.
- Log initialize and tool-call events.
- Resolve target server credentials at call time from user/team/org scope.
- Keep transport adapters behind a small interface so remote HTTP, Kubernetes stdio attach, and future transports do not leak into route handlers.

Kubernetes runtime pattern:

- Local MCP servers can run as Kubernetes Deployments.
- Secrets are created per installed server, or per multitenant catalog runtime.
- Streamable HTTP local servers get a Kubernetes Service.
- STDIO local servers require pod attach/exec-style transport.
- Runtime manager should restart local MCP deployments on service startup.

Wardn should adopt the catalog/install/gateway separation, but simplify the first MVP:

- Implement the internal registry/catalog first.
- Install and invoke remote Streamable HTTP servers first.
- Store package/stdio metadata but mark it not runnable until the Kubernetes runner is implemented.
- Defer OAuth, multitenant shared runtimes, deployment YAML editing, and dynamic enterprise credential exchange.
- Add invocation logging from day 0, with truncation/redaction.
- Prefer capability snapshots per installed server, not only per catalog entry. Archestra stores tools at catalog level, but Wardn should expect credentials/config to affect exposed capabilities.

Recommended Wardn MVP tables after reviewing Archestra:

- `mcp_registry_servers`
- `mcp_registry_server_versions`
- `mcp_installed_servers`
- `mcp_installed_server_secrets`
- `mcp_capability_snapshots`
- `mcp_tools`
- `mcp_invocations`
- `mcp_gateway_tokens` or future API-key/service-account table

Recommended status values:

- Registry version status: active, deprecated, deleted, unsupported.
- Install status: pending_config, validating, discovering_capabilities, installed, failed, disabled.
- Capability sync status: pending, running, succeeded, failed.
- Invocation status: allowed, blocked, succeeded, failed, timed_out.

## API Shape

Initial REST namespaces:

```text
/api/v1/health/live
/api/v1/health/ready
/api/v1/auth/*
/api/v1/users/me
/api/v1/workspaces/*
/api/v1/registry/servers/*
/api/v1/registry/import
/api/v1/registry/sync/official
/api/v1/workspaces/{workspace_id}/installed-servers/*
/api/v1/workspaces/{workspace_id}/installed-servers/{installed_server_id}/sync
/api/v1/workspaces/{workspace_id}/installed-servers/{installed_server_id}/capabilities
/api/v1/workspaces/{workspace_id}/installed-servers/{installed_server_id}/tools/{tool_name}/invoke
/api/v1/audit-events/*
```

OpenAPI should be treated as the first contract between backend and frontend. The Next.js app should consume generated or hand-maintained TypeScript clients only after contracts stabilize.

## Deferred API Namespaces

- `/api/v1/guardrails/*`
- `/api/v1/conversations/*`
- `/api/v1/knowledge-sources/*`
- `/api/v1/models/*`

## k3s Deployment Requirements

The app should be deployable to k3s with:

- API deployment with liveness and readiness probes.
- Web deployment with liveness/readiness probes.
- PostgreSQL dependency via external chart or existing cluster service.
- Migration job run before API rollout.
- ConfigMap for non-secret config.
- Secret for database URL, JWT signing secret, provider keys.
- Persistent volume only for PostgreSQL, not app containers.
- Resource requests/limits small enough for homelab/k3s nodes.

Recommended chart structure:

```text
deploy/helm/wardn-ai/
  Chart.yaml
  values.yaml
  templates/
    api-deployment.yaml
    api-service.yaml
    web-deployment.yaml
    web-service.yaml
    ingress.yaml
    migration-job.yaml
    secret.yaml
    configmap.yaml
```

## Testing Strategy

Backend first:

- Unit tests for MCP service logic, auth/token handling, and config.
- Unit tests for registry import/sync normalization.
- Unit tests for installability rules by transport type.
- Integration tests for FastAPI routes with PostgreSQL test database.
- Alembic migration test: upgrade from empty database to head.
- Contract smoke test: OpenAPI schema is generated and includes expected routers.
- MCP transport tests with fake MCP servers.
- Invocation audit tests.

Frontend later:

- API client tests.
- Auth flow tests.
- MCP registry and invocation interaction tests.

## Recommended First Implementation Slice

1. Create monorepo layout with `apps/api`, `apps/web`, `deploy/helm`, and `docs`.
2. Scaffold FastAPI app with settings, logging, health endpoints, and test setup.
3. Add SQLAlchemy session management, base model mixins, and Alembic.
4. Implement local auth tables and token flow.
5. Add workspace ownership model.
6. Add internal registry models and read/search endpoints.
7. Add `server.json` import endpoint and validation/normalization.
8. Add official registry sync client with cursor pagination and `updated_since`.
9. Add installed-server model and install/configure endpoints.
10. Add capability sync model and endpoint for installed servers.
11. Add MCP invocation gateway endpoint using a fake/test transport first.
12. Add audit event model and registry/install/gateway event recording.
13. Add real Streamable HTTP MCP transport adapter.
14. Add Helm chart with API, web placeholder, migration job, probes, and secrets.
15. Add minimal Next.js admin shell for login, registry browse/search, install/configure, capability list, and manual tool invocation.

## Open Questions

- Should the first auth API use access-token-only or refresh-token rotation from day 0?
- Will k3s PostgreSQL be an existing cluster service, a Helm-managed dependency, or both depending on values?
- Should MCP credentials be stored encrypted in DB from day 0, or only referenced through Kubernetes Secrets?
- What runner strategy should be used for package/STDIO servers: disabled initially, Kubernetes Job/Deployment, sidecar, or isolated worker pool?
- Should the gateway expose MCP-compatible endpoints to downstream clients, REST admin endpoints, or both in the MVP?
- Should the internal registry expose official-registry-compatible read endpoints under `/v0.1`, or only Wardn admin endpoints under `/api/v1` initially?

## Source Notes

- FastAPI recommends `APIRouter` for larger applications and lifespan context managers for startup/shutdown resource management.
- SQLAlchemy 2.x typed declarative mapping is the modern ORM baseline.
- Alembic is the SQLAlchemy migration tool and supports async-engine migration environments.
- Next.js App Router is the current file-system routing model using React Server Components.
- Kubernetes readiness/liveness/startup probes should be explicit for k3s deployments.
- MCP defines servers exposing tools, resources, and prompts, with HTTP authorization and Streamable HTTP transport guidance in the current spec line.
- The official MCP Registry is a public metadata catalog and API for discovering MCP servers; it uses `server.json` metadata, cursor pagination, `updated_since` sync, response-level status metadata, and supports public registry imports/subregistries.
