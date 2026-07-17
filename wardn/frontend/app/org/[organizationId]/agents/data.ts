import type { AgentListResponse } from "@/lib/api/generated/model";
import { backendJson } from "@/lib/api/server";

import type { AgentAvailableAssignments, AgentToolAssignments } from "./tool-types";

export async function getWorkspaceAgents(
  organizationId: string,
  workspaceId: string
): Promise<AgentListResponse["agents"]> {
  const payload = await backendJson<AgentListResponse>(
    `/api/v1/organizations/${encodeURIComponent(
      organizationId
    )}/workspaces/${encodeURIComponent(workspaceId)}/agents`
  );
  return payload.agents;
}

export async function getWorkspaceAgentAvailableTools(
  organizationId: string,
  workspaceId: string
): Promise<AgentAvailableAssignments> {
  const payload = await backendJson<AgentAvailableAssignments>(
    `/api/v1/organizations/${encodeURIComponent(
      organizationId
    )}/workspaces/${encodeURIComponent(workspaceId)}/agents/available-tools`
  );
  return { servers: payload.servers, tools: payload.tools };
}

export async function getWorkspaceAgentTools(
  organizationId: string,
  workspaceId: string,
  agentId: string
): Promise<AgentToolAssignments> {
  const payload = await backendJson<AgentToolAssignments>(
    `/api/v1/organizations/${encodeURIComponent(
      organizationId
    )}/workspaces/${encodeURIComponent(workspaceId)}/agents/${encodeURIComponent(agentId)}/tools`
  );
  return { servers: payload.servers, tools: payload.tools };
}
