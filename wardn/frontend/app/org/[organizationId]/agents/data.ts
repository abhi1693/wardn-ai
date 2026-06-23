import type { AgentListResponse, AgentToolListResponse } from "@/lib/api/generated/model";
import { backendCookieHeader, backendPath } from "@/lib/workspace-context";

export type AgentAvailableTool = {
  annotations?: Record<string, unknown>;
  configName: string;
  description: string;
  inputSchema: Record<string, unknown>;
  installationId: string;
  outputSchema?: Record<string, unknown> | null;
  serverName: string;
  title: string;
  toolName: string;
  toolSchemaId: string;
  workspaceId: string;
};

export async function getWorkspaceAgents(organizationId: string, workspaceId: string) {
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
) {
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
) {
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
      return [];
    }
    const payload = (await response.json()) as AgentToolListResponse;
    return payload.tools;
  } catch {
    return [];
  }
}
