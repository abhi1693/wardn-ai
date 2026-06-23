import type { AgentListResponse } from "@/lib/api/generated/model";
import { backendCookieHeader, backendPath } from "@/lib/workspace-context";

export async function getAgents(organizationId: string) {
  const cookie = await backendCookieHeader();
  try {
    const response = await fetch(
      backendPath(`/api/v1/organizations/${encodeURIComponent(organizationId)}/agents`),
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
