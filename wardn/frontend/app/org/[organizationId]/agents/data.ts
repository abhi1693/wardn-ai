import type { AgentListResponse } from "@/lib/api/generated/model";
import { backendCookieHeader, backendPath } from "@/lib/workspace-context";

import type { AgentAvailableTool, AgentToolAssignments } from "./tool-types";

export async function getWorkspaceAgents(
  organizationId: string,
  workspaceId: string
): Promise<AgentListResponse["agents"]> {
  const cookie = await backendCookieHeader();
  try {
    const response = await fetch(
      backendPath(
        `/api/v1/organizations/${encodeURIComponent(
          organizationId
        )}/workspaces/${encodeURIComponent(workspaceId)}/agents`
      ),
      {
        cache: "no-store",
        headers: cookie ? { cookie } : {},
      }
    );
    if (!response.ok) {
      return [];
    }
    const payload = (await response.json()) as AgentListResponse;
    return payload.agents;
  } catch {
    return [];
  }
}

export async function getWorkspaceAgentAvailableTools(
  organizationId: string,
  workspaceId: string
): Promise<AgentAvailableTool[]> {
  const cookie = await backendCookieHeader();
  try {
    const response = await fetch(
      backendPath(
        `/api/v1/organizations/${encodeURIComponent(
          organizationId
        )}/workspaces/${encodeURIComponent(workspaceId)}/agents/available-tools`
      ),
      {
        cache: "no-store",
        headers: cookie ? { cookie } : {},
      }
    );
    if (!response.ok) {
      return [];
    }
    const payload = (await response.json()) as { tools?: AgentAvailableTool[] };
    return payload.tools ?? [];
  } catch {
    return [];
  }
}

export async function getWorkspaceAgentTools(
  organizationId: string,
  workspaceId: string,
  agentId: string
): Promise<AgentToolAssignments> {
  const cookie = await backendCookieHeader();
  try {
    const response = await fetch(
      backendPath(
        `/api/v1/organizations/${encodeURIComponent(
          organizationId
        )}/workspaces/${encodeURIComponent(workspaceId)}/agents/${encodeURIComponent(
          agentId
        )}/tools`
      ),
      {
        cache: "no-store",
        headers: cookie ? { cookie } : {},
      }
    );
    if (!response.ok) {
      return { servers: [], tools: [] };
    }
    const payload = (await response.json()) as AgentToolAssignments;
    return {
      servers: payload.servers ?? [],
      tools: payload.tools ?? [],
    };
  } catch {
    return { servers: [], tools: [] };
  }
}
