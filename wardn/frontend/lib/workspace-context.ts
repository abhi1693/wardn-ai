import { cookies } from "next/headers";
import { cache } from "react";

import { backendJson } from "@/lib/api/server";

import {
  selectedOrganizationCookie,
  selectedWorkspaceCookie,
  type OrganizationOption,
  type WorkspaceContext,
  type WorkspaceOption,
} from "@/lib/workspace-types";

export {
  selectedOrganizationCookie,
  selectedWorkspaceCookie,
  type OrganizationOption,
  type WorkspaceContext,
  type WorkspaceOption,
};

type WorkspaceSelection = {
  organizationId?: string;
  workspaceId?: string;
};

export { backendCookieHeader, backendPath } from "@/lib/api/server";

export async function getWorkspaceContext(
  selection: WorkspaceSelection = {},
): Promise<WorkspaceContext> {
  const cookieStore = await cookies();
  const organizations = await getOrganizationOptions();
  const selectedOrganizationId =
    selection.organizationId ?? cookieStore.get(selectedOrganizationCookie)?.value;

  if (organizations.length === 0) {
    return {
      organizations,
      workspaces: [],
      selectedOrganization: null,
      selectedWorkspace: null,
    };
  }

  const requestedOrganization =
    organizations.find((organization) => organization.id === selectedOrganizationId) ?? null;
  const selectedOrganization =
    requestedOrganization ?? (selection.organizationId ? null : organizations[0] ?? null);
  const workspaces = selectedOrganization
    ? await getWorkspaceOptions(selectedOrganization.id)
    : [];
  const selectedWorkspaceId =
    selection.workspaceId ?? cookieStore.get(selectedWorkspaceCookie)?.value;
  const selectedWorkspace =
    workspaces.find((workspace) => workspace.id === selectedWorkspaceId) ??
    (selection.workspaceId ? null : workspaces[0] ?? null);

  return {
    organizations,
    workspaces,
    selectedOrganization,
    selectedWorkspace,
  };
}

export const getOrganizationOptions = cache(async (): Promise<OrganizationOption[]> => {
  const payload = await backendJson<{ organizations: OrganizationOption[] }>(
    "/api/v1/organizations"
  );
  return payload.organizations;
});

export const getWorkspaceOptions = cache(
  async (organizationId: string): Promise<WorkspaceOption[]> => {
    const payload = await backendJson<{ workspaces: WorkspaceOption[] }>(
      `/api/v1/organizations/${encodeURIComponent(organizationId)}/workspaces`
    );
    return payload.workspaces;
  }
);

export function workspaceBasePath(context: WorkspaceContext) {
  if (!context.selectedOrganization || !context.selectedWorkspace) {
    return "";
  }
  return `/org/${encodeURIComponent(context.selectedOrganization.id)}/workspace/${encodeURIComponent(
    context.selectedWorkspace.id
  )}`;
}

export function workspaceDashboardPath(context: WorkspaceContext) {
  const basePath = workspaceBasePath(context);
  return basePath ? `${basePath}/chat` : "/";
}

export function workspaceInstallPath(context: WorkspaceContext) {
  const basePath = workspaceBasePath(context);
  return basePath ? `${basePath}/install` : "";
}

export function workspaceRuntimePath(context: WorkspaceContext) {
  const basePath = workspaceBasePath(context);
  return basePath ? `${basePath}/runtime` : "";
}

export function workspaceObservabilityPath(context: WorkspaceContext) {
  const basePath = workspaceBasePath(context);
  return basePath ? `${basePath}/observability` : "";
}

export function workspaceMcpRegistryPath(
  context: WorkspaceContext,
  suffix: string,
) {
  if (!context.selectedOrganization || !context.selectedWorkspace) {
    return "";
  }
  return `/api/v1/organizations/${encodeURIComponent(
    context.selectedOrganization.id
  )}/workspaces/${encodeURIComponent(context.selectedWorkspace.id)}/mcp/registry${suffix}`;
}

export function workspaceMcpRuntimePath(
  context: WorkspaceContext,
  suffix: string,
) {
  if (!context.selectedOrganization || !context.selectedWorkspace) {
    return "";
  }
  return `/api/v1/organizations/${encodeURIComponent(
    context.selectedOrganization.id
  )}/workspaces/${encodeURIComponent(context.selectedWorkspace.id)}/mcp/runtime${suffix}`;
}

export function workspaceObservabilityApiPath(
  context: WorkspaceContext,
  suffix: string,
) {
  if (!context.selectedOrganization || !context.selectedWorkspace) {
    return "";
  }
  return `/api/v1/organizations/${encodeURIComponent(
    context.selectedOrganization.id
  )}/workspaces/${encodeURIComponent(context.selectedWorkspace.id)}/observability${suffix}`;
}

export function organizationMcpRegistryPath(
  context: WorkspaceContext,
  suffix: string,
) {
  if (!context.selectedOrganization) {
    return "";
  }
  return `/api/v1/organizations/${encodeURIComponent(
    context.selectedOrganization.id
  )}/mcp/registry${suffix}`;
}
