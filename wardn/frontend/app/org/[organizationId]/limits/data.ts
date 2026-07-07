import type {
  ResourceLimitListResponse,
  ResourceLimitRead,
  UserRead,
  WorkspaceRead,
} from "@/lib/api/generated/model";
import { backendCookieHeader, backendPath } from "@/lib/workspace-context";

export async function getCurrentUser() {
  const cookie = await backendCookieHeader();
  try {
    const response = await fetch(backendPath("/api/v1/auth/me"), {
      cache: "no-store",
      headers: cookie ? { cookie } : {},
    });
    if (!response.ok) {
      return null;
    }
    return (await response.json()) as UserRead;
  } catch {
    return null;
  }
}

export async function getLimits() {
  const cookie = await backendCookieHeader();
  try {
    const response = await fetch(backendPath("/api/v1/limits"), {
      cache: "no-store",
      headers: cookie ? { cookie } : {},
    });
    if (!response.ok) {
      return [] as ResourceLimitRead[];
    }
    const payload = (await response.json()) as ResourceLimitListResponse;
    return payload.limits;
  } catch {
    return [] as ResourceLimitRead[];
  }
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
