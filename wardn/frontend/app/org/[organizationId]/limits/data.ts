import type {
  ResourceLimitListResponse,
  ResourceLimitRead,
  WorkspaceRead,
} from "@/lib/api/generated/model";
import { backendJson } from "@/lib/api/server";

export async function getLimits() {
  const payload = await backendJson<ResourceLimitListResponse>("/api/v1/limits");
  return payload.limits;
}

export function limitBelongsToOrganization(
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
