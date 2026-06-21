# Wardn AI

Wardn AI is starting as a backend-first unified MCP registry and gateway.

The first implementation slice focuses on the backend foundation, users, local credentials, and API tokens. MCP registry/gateway work comes after the identity base is stable. Guardrails, chat, and RAG are intentionally deferred.

## Repository Layout

```text
wardn/
  backend/   FastAPI backend service
  frontend/  Monolithic Next.js frontend app
docs/
```

## Backend

```bash
cd wardn/backend
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

Health endpoints:

- `GET /api/v1/health/live`
- `GET /api/v1/health/ready`

## Frontend

```bash
cd wardn/frontend
npm install
npm run dev
```

## API Client Generation

The frontend API client is generated from the FastAPI OpenAPI schema with Orval.

```bash
npm run web:api:generate
```

This writes:

- `wardn/frontend/openapi/wardn-api.json`
- `wardn/frontend/lib/api/generated/`

## Database

The backend is wired for PostgreSQL through SQLAlchemy and Alembic.

```bash
cd wardn/backend
alembic upgrade head
```

## Management Commands

```bash
cd wardn/backend
python -m app.manage createsuperuser
```
