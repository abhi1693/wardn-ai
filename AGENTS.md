# Repository Guidelines

## Project Structure & Module Organization

Wardn is split under `wardn/`:

- `wardn/backend/`: FastAPI API service, SQLAlchemy models, Alembic migrations, management commands, and backend tests.
- `wardn/frontend/`: monolithic Next.js application, shadcn-style UI components, API proxy routes, and generated Orval client code.
- `docs/`: local design and research notes. Keep private research out of committed source unless explicitly intended.

Backend modules live under `wardn/backend/app/modules/` and should stay domain-focused, for example `users`, `mcp_registry`, `mcp_gateway`, and `mcp_runtime`. Frontend pages live in `wardn/frontend/app/`; shared UI primitives are in `wardn/frontend/components/ui/`.

## Build, Test, and Development Commands

- `cd wardn/backend && ../../.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000`: run the backend locally.
- `cd wardn/backend && ../../.venv/bin/alembic upgrade head`: apply database migrations.
- `cd wardn/backend && ../../.venv/bin/pytest`: run backend tests.
- `npm run web:dev`: run the frontend dev server.
- `npm run web:build`: build the frontend.
- `npm run web:lint`: run frontend ESLint.
- `cd wardn/backend && ../../.venv/bin/python -m app.openapi --output ../frontend/openapi/wardn-api.json && cd ../frontend && npm run api:generate`: regenerate OpenAPI and Orval client types.

## Coding Style & Naming Conventions

Backend code targets Python 3.12, uses Ruff with a 100-character line length, and should keep FastAPI routers thin with domain logic in services/repositories. Use snake_case for Python modules, functions, and fields.

Frontend code uses TypeScript, React, Next.js App Router, ESLint, and shadcn-style primitives. Use PascalCase for components, camelCase for helpers, and route folders that match Next.js conventions.

## Testing Guidelines

Backend tests use `pytest` and `pytest-asyncio`; place tests in `wardn/backend/tests/` with names like `test_mcp_gateway.py`. Add focused tests for service behavior, OpenAPI contracts, and error paths. For frontend changes, run `npm run web:lint` and `npm run web:build`.

## Release Checklist

Use this checklist when asked to release Wardn AI and related home-lab workloads.

1. Verify the Wardn AI repo before release:
   - Run `npm run backend:lint`.
   - Run `npm run backend:test`.
   - Run `npm run web:api:generate`.
   - Run `npm run web:lint`.
   - Run `npm run web:build`.
   - Commit and push Wardn AI changes to `master`.

2. Publish the release:
   - Create the next Wardn AI GitHub release tag, for example `v0.0.x`.
   - Watch the container image workflow until it succeeds.

3. Confirm images before updating workloads:
   - Check the expected GHCR tags exist for Wardn AI backend and frontend.
   - Check the `registry.home/ghcr.io/...` mirror resolves those same tags.

4. Update home-lab workloads:
   - Work in `/home/asaharan/PycharmProjects/home-lab`.
   - Update only Wardn AI related manifests under `kubernetes/projects/applications/apps/wardn-ai`.
   - Run `kubectl kustomize kubernetes/projects/applications/apps/wardn-ai`.
   - Commit and push home-lab changes to `master`.

5. Do not apply Kubernetes workloads manually unless explicitly asked.

## Commit & Pull Request Guidelines

Recent commits use short imperative summaries, for example `Implement MCP install validation flow`. Keep commits focused and include generated OpenAPI/Orval files when API schemas change.

Pull requests should describe the user-facing change, backend/API impact, migrations, and verification commands. Include screenshots for UI changes and call out any configuration or secret-handling changes.

## Security & Configuration Tips

Never commit credentials, service tokens, local database dumps, or private research notes. Keep runtime secrets in local environment files, database-backed secret config, or deployment secrets. Treat MCP server credentials as sensitive, even when a tool only needs them for validation.
