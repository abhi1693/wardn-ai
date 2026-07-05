import type {
  AgentAvailableToolListResponse,
  AgentListResponse,
  GuardrailPolicyListResponse,
  GuardrailPolicyRead,
  MCPServerInstallationListResponse,
} from "@/lib/api/generated/model";
import { backendCookieHeader, backendPath } from "@/lib/workspace-context";

export type GuardrailPolicyRecord = {
  policy: GuardrailPolicyRead;
};

export type GuardrailAgentOption = {
  id: string;
  name: string;
  workspaceId: string;
};

export type GuardrailServerOption = {
  configName: string;
  installationId: string;
  label: string;
  serverName: string;
  workspaceId: string;
};

export type GuardrailToolOption = {
  configName: string;
  installationId: string;
  label: string;
  serverName: string;
  toolName: string;
  toolSchemaId: string;
  workspaceId: string;
};

async function fetchBackend<T>(path: string): Promise<T | null> {
  const cookie = await backendCookieHeader();
  try {
    const response = await fetch(backendPath(path), {
      cache: "no-store",
      headers: cookie ? { cookie } : {},
    });
    if (!response.ok) {
      return null;
    }
    return (await response.json()) as T;
  } catch {
    return null;
  }
}

export async function getWorkspaceGuardrailPolicies(
  organizationId: string,
  workspaceId: string,
) {
  const payload = await fetchBackend<GuardrailPolicyListResponse>(
    `/api/v1/organizations/${encodeURIComponent(
      organizationId
    )}/workspaces/${encodeURIComponent(workspaceId)}/guardrails/policies`
  );
  return payload?.policies ?? [];
}

export async function getGuardrailPolicyRecords(
  organizationId: string,
  workspaceId: string,
) {
  const policies = await getWorkspaceGuardrailPolicies(organizationId, workspaceId);
  return policies
    .map((policy) => ({ policy }))
    .sort((left, right) => {
    const priorityCompare = left.policy.priority - right.policy.priority;
    if (priorityCompare !== 0) {
      return priorityCompare;
    }
    return left.policy.name.localeCompare(right.policy.name);
  });
}

export async function getGuardrailWorkspaceOptions(
  organizationId: string,
  workspaceId: string,
) {
  const [agentsPayload, serversPayload, availableToolsPayload] = await Promise.all([
    fetchBackend<AgentListResponse>(
      `/api/v1/organizations/${encodeURIComponent(
        organizationId
      )}/workspaces/${encodeURIComponent(workspaceId)}/agents`
    ),
    fetchBackend<MCPServerInstallationListResponse>(
      `/api/v1/organizations/${encodeURIComponent(
        organizationId
      )}/workspaces/${encodeURIComponent(workspaceId)}/mcp/registry/installed-servers`
    ),
    fetchBackend<AgentAvailableToolListResponse>(
      `/api/v1/organizations/${encodeURIComponent(
        organizationId
      )}/workspaces/${encodeURIComponent(workspaceId)}/agents/available-tools`
    ),
  ]);

  const agents: GuardrailAgentOption[] = (agentsPayload?.agents ?? []).map((agent) => ({
    id: agent.id,
    name: agent.name,
    workspaceId,
  }));
  const servers: GuardrailServerOption[] = (serversPayload?.installations ?? []).map(
    (installation) => ({
      configName: installation.configName,
      installationId: installation.id,
      label: `${installation.configName} (${installation.server.title || installation.serverName})`,
      serverName: installation.serverName,
      workspaceId,
    })
  );
  const tools: GuardrailToolOption[] = (availableToolsPayload?.tools ?? []).map((tool) => ({
    configName: tool.configName,
    installationId: tool.installationId,
    label: `${tool.toolName} (${tool.configName})`,
    serverName: tool.serverName,
    toolName: tool.toolName,
    toolSchemaId: tool.toolSchemaId,
    workspaceId,
  }));

  return { agents, servers, tools };
}
