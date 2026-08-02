import { notFound } from "next/navigation";

import { AppShell } from "@/app/components/app-shell";
import {
  OrganizationDashboard,
  type WorkspaceDashboardDigest,
} from "@/components/organisms/organization-dashboard";
import type {
  AgentListResponse,
  LLMProviderCredentialListResponse,
  MCPCatalogSourceListResponse,
  MCPServerInstallationListResponse,
  MCPServerInstallationRead,
  ResourceLimitListResponse,
  ResourceLimitRead,
  UsageSummaryResponse,
  WorkspaceRead,
} from "@/lib/api/generated/model";
import { backendJson } from "@/lib/api/server";
import {
  getWorkspaceContext,
  type WorkspaceContext,
} from "@/lib/workspace-context";

type OrganizationDashboardPageProps = {
  params: Promise<{ organizationId: string }>;
};

async function optionalBackendJson<T>(path: string) {
  try {
    return await backendJson<T>(path, { timeoutMs: 15_000 });
  } catch {
    return null;
  }
}

function runtimeLabel(value: string) {
  const normalized = value.toLowerCase();
  if (normalized === "remote") {
    return "Remote endpoint";
  }
  if (normalized === "oci") {
    return "OCI";
  }
  if (normalized === "npm") {
    return "NPM";
  }
  if (normalized === "uvx") {
    return "UVX";
  }
  return value;
}

function installationNeedsAttention(installation: MCPServerInstallationRead) {
  return installation.status !== "enabled" || Boolean(installation.installError);
}

function limitBelongsToOrganization(
  limit: ResourceLimitRead,
  organizationId: string,
  workspaces: WorkspaceRead[],
) {
  if (limit.scopeType === "organization") {
    return limit.scopeId === organizationId;
  }
  if (limit.scopeType === "workspace" && limit.scopeId) {
    return workspaces.some((workspace) => workspace.id === limit.scopeId);
  }
  return false;
}

async function getCatalogSources(organizationId: string) {
  const payload = await optionalBackendJson<MCPCatalogSourceListResponse>(
    `/api/v1/organizations/${encodeURIComponent(organizationId)}/mcp/catalog/sources`
  );
  return payload?.sources ?? null;
}

async function getProviderCredentials(organizationId: string) {
  const payload = await optionalBackendJson<LLMProviderCredentialListResponse>(
    `/api/v1/organizations/${encodeURIComponent(organizationId)}/llm/provider-credentials`
  );
  return payload?.credentials ?? null;
}

async function getResourceLimits(context: WorkspaceContext) {
  const organization = context.selectedOrganization;
  if (!organization) {
    return null;
  }
  const payload = await optionalBackendJson<ResourceLimitListResponse>("/api/v1/limits");
  return (
    payload?.limits.filter((limit) =>
      limitBelongsToOrganization(limit, organization.id, context.workspaces)
    ) ?? null
  );
}

async function getUsageSummary(organizationId: string) {
  return optionalBackendJson<UsageSummaryResponse>(
    `/api/v1/organizations/${encodeURIComponent(organizationId)}/usage/summary`
  );
}

async function getWorkspaceDigest(
  organizationId: string,
  workspace: WorkspaceRead,
): Promise<WorkspaceDashboardDigest> {
  const organizationPath = `/api/v1/organizations/${encodeURIComponent(organizationId)}`;
  const workspacePath = `${organizationPath}/workspaces/${encodeURIComponent(workspace.id)}`;
  const [installationsPayload, agentsPayload] = await Promise.all([
    optionalBackendJson<MCPServerInstallationListResponse>(
      `${workspacePath}/mcp/registry/installed-servers`
    ),
    optionalBackendJson<AgentListResponse>(`${workspacePath}/agents`),
  ]);
  const installations = installationsPayload?.installations ?? null;
  const agents = agentsPayload?.agents ?? null;
  const runtimeCounts =
    installations?.reduce<Record<string, number>>((counts, installation) => {
      const label = runtimeLabel(installation.installType);
      counts[label] = (counts[label] ?? 0) + 1;
      return counts;
    }, {}) ?? null;

  return {
    activeAgentCount: agents?.filter((agent) => agent.isActive).length ?? null,
    agentCount: agents?.length ?? null,
    agentLoadFailed: agents === null,
    attentionInstallationCount:
      installations?.filter((installation) => installationNeedsAttention(installation)).length ??
      null,
    enabledInstallationCount:
      installations?.filter((installation) => installation.status === "enabled").length ?? null,
    installationCount: installations?.length ?? null,
    installationLoadFailed: installations === null,
    runtimeCounts,
    toolCount: agents?.reduce((sum, agent) => sum + agent.toolCount, 0) ?? null,
    updateCount: installations?.filter((installation) => installation.updateAvailable).length ?? null,
    workspace,
  };
}

export default async function OrganizationDashboardPage({
  params,
}: OrganizationDashboardPageProps) {
  const { organizationId } = await params;
  const workspaceContext = await getWorkspaceContext({ organizationId });
  const organization = workspaceContext.selectedOrganization;

  if (!organization) {
    notFound();
  }

  const [catalogSources, providerCredentials, resourceLimits, usage, workspaceDigests] =
    await Promise.all([
      getCatalogSources(organization.id),
      getProviderCredentials(organization.id),
      getResourceLimits(workspaceContext),
      getUsageSummary(organization.id),
      Promise.all(
        workspaceContext.workspaces.map((workspace) =>
          getWorkspaceDigest(organization.id, workspace)
        )
      ),
    ]);

  return (
    <AppShell
      active="org-dashboard"
      eyebrow="Organization"
      title="Dashboard"
      workspaceContext={workspaceContext}
    >
      <OrganizationDashboard
        catalogSources={catalogSources}
        organization={organization}
        providerCredentials={providerCredentials}
        resourceLimits={resourceLimits}
        usage={usage}
        workspaceDigests={workspaceDigests}
      />
    </AppShell>
  );
}
