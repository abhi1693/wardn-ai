# Wardn Runtime Adapter

The runtime adapter exposes a stateful HTTP boundary for stdio MCP servers.

Initial endpoints:

- `GET /healthz`
- `GET /readyz`
- `POST /mcp`
- `POST /shutdown`

Configuration is environment-based:

- `WARDN_RUNTIME_COMMAND`
- `WARDN_RUNTIME_ARGS_JSON`
- `WARDN_RUNTIME_CWD`
- `WARDN_RUNTIME_STARTUP_TIMEOUT_SECONDS`
- `WARDN_RUNTIME_REQUEST_TIMEOUT_SECONDS`

The adapter starts one stdio MCP subprocess, initializes it during app startup, and forwards
JSON-RPC requests over stdio.

Run locally:

```bash
WARDN_RUNTIME_COMMAND=python \
WARDN_RUNTIME_ARGS_JSON='["/path/to/server.py"]' \
wardn-runtime-adapter
```
