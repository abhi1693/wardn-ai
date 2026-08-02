import type { AgentListResponse } from "@/lib/api/generated/model";
import { backendJson } from "@/lib/api/server";

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
