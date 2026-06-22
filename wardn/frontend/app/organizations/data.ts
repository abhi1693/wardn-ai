import type {
  OrganizationListResponse,
  OrganizationRead,
  WorkspaceListResponse,
  WorkspaceRead,
} from "@/lib/api/generated/model";
import { backendCookieHeader, backendPath, getWorkspaceContext } from "@/lib/workspace-context";

export async function getOrganizations() {
  const cookie = await backendCookieHeader();
  try {
    const response = await fetch(backendPath("/api/v1/organizations"), {
      cache: "no-store",
      headers: cookie ? { cookie } : {},
    });
    if (!response.ok) {
      return [];
    }
    const payload = (await response.json()) as OrganizationListResponse;
    return payload.organizations;
  } catch {
    return [];
  }
}

export async function getOrganization(organizationId: string) {
  const cookie = await backendCookieHeader();
  try {
    const response = await fetch(
      backendPath(`/api/v1/organizations/${encodeURIComponent(organizationId)}`),
      {
        cache: "no-store",
        headers: cookie ? { cookie } : {},
      }
    );
    if (!response.ok) {
      return null;
    }
    return (await response.json()) as OrganizationRead;
  } catch {
    return null;
  }
}

export async function getWorkspaces(organizationId: string) {
  const cookie = await backendCookieHeader();
  try {
    const response = await fetch(
      backendPath(`/api/v1/organizations/${encodeURIComponent(organizationId)}/workspaces`),
      {
        cache: "no-store",
        headers: cookie ? { cookie } : {},
      }
    );
    if (!response.ok) {
      return [];
    }
    const payload = (await response.json()) as WorkspaceListResponse;
    return payload.workspaces;
  } catch {
    return [];
  }
}

export async function getWorkspace(organizationId: string, workspaceId: string) {
  const cookie = await backendCookieHeader();
  try {
    const response = await fetch(
      backendPath(
        `/api/v1/organizations/${encodeURIComponent(organizationId)}/workspaces/${encodeURIComponent(
          workspaceId
        )}`
      ),
      {
        cache: "no-store",
        headers: cookie ? { cookie } : {},
      }
    );
    if (!response.ok) {
      return null;
    }
    return (await response.json()) as WorkspaceRead;
  } catch {
    return null;
  }
}

export { getWorkspaceContext };
