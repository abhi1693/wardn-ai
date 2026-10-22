# MCP runtime dependencies

The image supplies Node.js 26.12.1, Python, uv, Deno and Supergateway for isolated
MCP server execution. `package.json` and `package-lock.json` lock the gateway's
complete runtime dependency tree; Docker installs it with `npm ci --omit=dev`.
The application release tag remains authoritative; this private package keeps a
development version placeholder.

Supergateway 4.2.0 pins older MCP packages. Same-major overrides select SDK
1.32.1, client/server 2.3.1 and Node middleware 2.1.1 to fix the published
[client credential/transport advisories](https://github.com/advisories/GHSA-6prh-2h8m-c8cw)
and [server isolation advisories](https://github.com/advisories/GHSA-jm63-cq47-j5jp).
Keep these overrides until the gateway declares fixed versions itself; no
advisories or severity gates are suppressed.

From this directory, run `npm ci --ignore-scripts`, `npm test` and `npm audit`.
The functional test starts only loopback services and a deterministic local
stdio server, then checks the production Streamable HTTP flags, initialization,
tool discovery and a tool call with the actual gateway and SDKs. CI requires this
test and a separate moderate-or-higher audit before image builds/publication.
No application credentials or external MCP endpoints are used.
