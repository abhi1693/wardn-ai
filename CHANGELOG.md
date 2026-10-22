# Changelog

## 0.0.38 (release preparation)

- Update all runtime, development and optional package manifests and regenerate
  their transitive lockfiles from current package registries.
- Upgrade Next.js and its tooling together to 16.4.2, React to 19.3.1 and the
  supported build/runtime Node.js line to 26.12.1.
- Keep ESLint at 9.39.5 because the current React, import and accessibility plugins
  do not support ESLint 10. Keep TypeScript at 6.0.3 because typescript-eslint
  requires TypeScript below 6.1. These are explicit compatibility limits.
- Reuse the tested, licensed local braces depth fix for CVE-2026-93687 until an
  upstream fixed release exists; include dependency security regression tests.

This change prepares the next patch release. Tags, releases, image publication
and deployment require the subsequent release workflow.

The backend keeps its setuptools-scm dynamic version and the private frontend
keeps its development placeholder. The release tag remains authoritative.

Update the embedded MCP runtime's npm and Supergateway packages and the pinned
uv, Node.js, Python, Go and Deno build/runtime artifacts. The WhatsApp bridge
keeps its reviewed upstream application source revision; its module lockfiles
are maintained alongside the Docker build so dependency upgrades are reviewed
and reproduced rather than fetched with floating `go get` during image builds.

Cypress stays at the current compatible 15.21.1 because the latest cypress-axe
1.7.0 peer range excludes Cypress 16. Accessibility coverage remains enabled;
no peer checks are bypassed. Antora extensions retain their existing vendor
alpha/beta channels because those packages have no stable release.

Upgrade the AI SDK UI pair together to ai 7.0.150 / @ai-sdk/react 4.0.154.
The existing ESM useChat/DefaultChatTransport integration is compatible with the
vendor migration contract; browser tests retain custom backend stream coverage.
Pydantic now omits its generic decimal regex from generated schema metadata;
regenerate the OpenAPI/client/docs attachments with the updated backend.

Lock the Supergateway runtime separately and update its same-major MCP SDK
security overrides, with a real stdio-to-HTTP initialization/discovery/tool-call
smoke test and an unsuppressed npm audit gate before image publication.

Install the shared atomic library explicitly when copying the Node 26 binary
into the Python/Deno runtimes; the full official Node image already provides it.

Pin the current official Python 3.12.15 API/worker and Python 3.13.17 MCP
runtime patch images, with verified ARM64 and AMD64 manifests.

Use native visible-text names for command search, expanded navigation links and
usage disclosures, keeping disclosure state in aria-expanded. The updated axe
checks cover both themes and compact navigation without disabling any rules.
