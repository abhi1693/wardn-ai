import type {
  AgentAvailableToolListResponse,
  GuardrailPolicyListResponse,
  GuardrailPolicyRead,
  MCPServerInstallationListResponse,
} from "@/lib/api/generated/model";
import { backendJson } from "@/lib/api/server";

export type GuardrailPolicyRecord = {
  policy: GuardrailPolicyRead;
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

export async function getWorkspaceGuardrailPolicies(
  organizationId: string,
  workspaceId: string,
) {
  const payload = await backendJson<GuardrailPolicyListResponse>(
    `/api/v1/organizations/${encodeURIComponent(
      organizationId
    )}/workspaces/${encodeURIComponent(workspaceId)}/guardrails/policies`
  );
  return payload.policies;
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
  const [serversPayload, availableToolsPayload] = await Promise.all([
    backendJson<MCPServerInstallationListResponse>(
      `/api/v1/organizations/${encodeURIComponent(
        organizationId
      )}/workspaces/${encodeURIComponent(workspaceId)}/mcp/registry/installed-servers`
    ),
    backendJson<AgentAvailableToolListResponse>(
      `/api/v1/organizations/${encodeURIComponent(
        organizationId
      )}/workspaces/${encodeURIComponent(workspaceId)}/agents/available-tools`
    ),
  ]);

  const servers: GuardrailServerOption[] = serversPayload.installations.map(
    (installation) => ({
      configName: installation.configName,
      installationId: installation.id,
      label: `${installation.configName} (${installation.server.title || installation.serverName})`,
      serverName: installation.serverName,
      workspaceId,
    })
  );
  const tools: GuardrailToolOption[] = availableToolsPayload.tools.map((tool) => ({
    configName: tool.configName,
    installationId: tool.installationId,
    label: `${tool.toolName} (${tool.configName})`,
    serverName: tool.serverName,
    toolName: tool.toolName,
    toolSchemaId: tool.toolSchemaId,
    workspaceId,
  }));

  return { servers, tools };
}
