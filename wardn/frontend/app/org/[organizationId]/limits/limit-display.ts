import type {
  OrganizationRead,
  ResourceLimitRead,
  WorkspaceRead,
} from "@/lib/api/generated/model";

export type LimitScopeType = "organization" | "workspace";

export const knownLimitKeys: Array<{
  value: string;
  label: string;
  scopes: LimitScopeType[];
  defaultScope: LimitScopeType;
}> = [
  {
    value: "workspaces.per_organization",
    label: "Workspaces per organization",
    scopes: ["organization"],
    defaultScope: "organization",
  },
  {
    value: "workspaces.created_per_user",
    label: "Workspaces created per user",
    scopes: ["organization"],
    defaultScope: "organization",
  },
  {
    value: "agents.per_organization",
    label: "Agents per organization",
    scopes: ["organization"],
    defaultScope: "organization",
  },
  {
    value: "agents.per_workspace",
    label: "Agents per workspace",
    scopes: ["workspace", "organization"],
    defaultScope: "workspace",
  },
  {
    value: "agents.per_workspace_per_user",
    label: "Agents per workspace per user",
    scopes: ["workspace", "organization"],
    defaultScope: "workspace",
  },
  {
    value: "workspace_conversations.per_workspace",
    label: "Conversations per workspace",
    scopes: ["workspace", "organization"],
    defaultScope: "workspace",
  },
  {
    value: "workspace_conversations.per_workspace_per_user",
    label: "Conversations per workspace per user",
    scopes: ["workspace", "organization"],
    defaultScope: "workspace",
  },
  {
    value: "guardrail_policies.per_workspace",
    label: "Guardrail policies per workspace",
    scopes: ["workspace", "organization"],
    defaultScope: "workspace",
  },
  {
    value: "guardrail_policies.per_workspace_per_user",
    label: "Guardrail policies per workspace per user",
    scopes: ["workspace", "organization"],
    defaultScope: "workspace",
  },
  {
    value: "mcp_catalog_sources.per_organization",
    label: "MCP catalog sources per organization",
    scopes: ["organization"],
    defaultScope: "organization",
  },
  {
    value: "mcp_server_versions.per_organization",
    label: "MCP server versions per organization",
    scopes: ["organization"],
    defaultScope: "organization",
  },
  {
    value: "mcp_server_installations.per_workspace",
    label: "MCP server installs per workspace",
    scopes: ["workspace", "organization"],
    defaultScope: "workspace",
  },
  {
    value: "secret_stores.per_organization",
    label: "Secret stores per organization",
    scopes: ["organization"],
    defaultScope: "organization",
  },
  {
    value: "secret_stores.per_workspace",
    label: "Secret stores per workspace",
    scopes: ["workspace", "organization"],
    defaultScope: "workspace",
  },
  {
    value: "secret_handles.per_organization",
    label: "Secret handles per organization",
    scopes: ["organization"],
    defaultScope: "organization",
  },
  {
    value: "secret_handles.per_workspace",
    label: "Secret handles per workspace",
    scopes: ["workspace", "organization"],
    defaultScope: "workspace",
  },
  {
    value: "llm_provider_credentials.per_organization",
    label: "LLM credentials per organization",
    scopes: ["organization"],
    defaultScope: "organization",
  },
  {
    value: "llm_provider_credentials.per_workspace",
    label: "LLM credentials per workspace",
    scopes: ["workspace", "organization"],
    defaultScope: "workspace",
  },
  {
    value: "llm_provider_credentials.per_user",
    label: "LLM credentials per user",
    scopes: ["organization"],
    defaultScope: "organization",
  },
];

export function displayLimitKey(value: string) {
  return knownLimitKeys.find((entry) => entry.value === value)?.label ?? value;
}

export function formatDate(value: string) {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export function scopeLabel(
  limit: ResourceLimitRead,
  organizations: OrganizationRead[],
  workspaces: WorkspaceRead[],
) {
  const organizationById = new Map(
    organizations.map((organization) => [organization.id, organization])
  );
  const workspaceById = new Map(workspaces.map((workspace) => [workspace.id, workspace]));

  if (limit.scopeType === "organization" && limit.scopeId) {
    return organizationById.get(limit.scopeId)?.name ?? limit.scopeId;
  }
  if (limit.scopeType === "workspace" && limit.scopeId) {
    const workspace = workspaceById.get(limit.scopeId);
    const organization = workspace ? organizationById.get(workspace.organizationId) : null;
    return workspace && organization
      ? `${organization.name} / ${workspace.name}`
      : limit.scopeId ?? "";
  }
  return limit.scopeId ?? "";
}
