# PulseMCP Org Catalog Integration

Date: 2026-06-22

## Summary

PulseMCP can be used as an upstream catalog source for organization-wide MCP
server discovery. The right first integration point is the existing Wardn MCP
registry, not a parallel table for server records.

Wardn already stores org-scoped MCP catalog entries in
`mcp_server_versions`, keyed by organization, server name, and version. PulseMCP
returns registry-compatible `server.json` documents plus Pulse-specific metadata,
so those documents can be synced into the existing table and served through the
current org registry APIs.

## PulseMCP API Shape

Relevant PulseMCP API documentation:

- Public docs: https://www.pulsemcp.com/api/docs/v0.1
- Base URL: `https://api.pulsemcp.com`
- List endpoint: `GET /v0.1/servers`
- Auth headers:
  - `X-API-Key`
  - `X-Tenant-ID`
- Pagination: cursor-based via `metadata.nextCursor`
- Page size: `limit`, documented as 1-100
- Incremental sync: `updated_since` RFC3339 timestamp
- Latest-only catalog: `version=latest`

PulseMCP recommends local caching because the API is not intended to be in the
critical path for user-facing application requests.

## Metadata Mapping

Each PulseMCP response item has:

- `server`: the registry server document
- `_meta["com.pulsemcp/server"]`: server-level enrichments, such as visitor
  estimates and official status
- `_meta["com.pulsemcp/server-version"]`: version-level metadata, such as
  source, status, timestamps, and `isLatest`

Wardn should preserve the Pulse metadata in `server_json["_meta"]` for future UI
ranking and filtering. The version-level fields can also be mapped into Wardn's
existing columns:

- `status`
- `status_message`
- `published_at`
- `status_changed_at`
- `is_latest`

## Recommended Wardn Design

Use `mcp_server_versions` as the actual org catalog table. Add a smaller source
configuration table for sync state:

- `mcp_catalog_sources`
  - `organization_id`
  - `name`
  - `provider`: `official_registry`, `pulsemcp`, or `custom`
  - `base_url`
  - `tenant_id`
  - `sync_mode`: `latest_only` or `full_etl`
  - `secret_config`: API-key material or a later secret reference
  - `last_success_at`
  - `last_synced_updated_since`
  - `last_error`
  - `is_enabled`

A separate `mcp_catalog_entries` staging table is only worth adding if Wardn
needs an approval workflow where PulseMCP entries are reviewed before promotion
into the installable catalog. Without that workflow, duplicating server records
adds complexity without buying much.

## Initial Implementation Scope

1. Keep the existing registry API response shape.
2. Extend the sync command to support PulseMCP headers and parameters.
3. Parse PulseMCP version metadata when deciding status and latest version.
4. Add source configuration storage for the later admin UI and scheduled sync.

Future work:

- Organization admin API for CRUD on catalog sources.
- Scheduled sync job using `last_synced_updated_since`.
- UI filters and ranking using PulseMCP enrichments.
- Optional approval/staging workflow for externally sourced catalog entries.
