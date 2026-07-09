import { cookies } from "next/headers";

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

const backendUrl = process.env.WARDN_BACKEND_URL ?? "http://127.0.0.1:8000";

type WorkspaceSelection = {
  organizationId?: string;
  workspaceId?: string;
};

export function backendPath(path: string) {
  return `${backendUrl}${path}`;
}

export async function backendCookieHeader() {
  const cookieStore = await cookies();
  return cookieStore
    .getAll()
    .map((cookie) => `${cookie.name}=${cookie.value}`)
    .join("; ");
}

async function fetchBackendJson<T>(path: string): Promise<T | null> {
  const cookieHeader = await backendCookieHeader();
  try {
    const response = await fetch(backendPath(path), {
      cache: "no-store",
      headers: cookieHeader ? { cookie: cookieHeader } : {},
    });
    if (!response.ok) {
      return null;
    }
    return (await response.json()) as T;
  } catch {
    return null;
  }
}

export async function getWorkspaceContext(
  selection: WorkspaceSelection = {},
): Promise<WorkspaceContext> {
  const cookieStore = await cookies();
  const organizationsPayload = await fetchBackendJson<{ organizations: OrganizationOption[] }>(
    "/api/v1/organizations"
  );
  const organizations = organizationsPayload?.organizations ?? [];
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

  const workspacePayloads = await Promise.all(
    organizations.map((organization) =>
      fetchBackendJson<{ workspaces: WorkspaceOption[] }>(
        `/api/v1/organizations/${encodeURIComponent(organization.id)}/workspaces`
      )
    )
  );
  const workspaces = workspacePayloads.flatMap((payload) => payload?.workspaces ?? []);
  const selectedWorkspaceId =
    selection.workspaceId ?? cookieStore.get(selectedWorkspaceCookie)?.value;
  const requestedOrganization =
    organizations.find((organization) => organization.id === selectedOrganizationId) ?? null;
  const workspaceCandidates = requestedOrganization
    ? workspaces.filter((workspace) => workspace.organizationId === requestedOrganization.id)
    : workspaces;
  const selectedWorkspace =
    workspaceCandidates.find((workspace) => workspace.id === selectedWorkspaceId) ??
    workspaceCandidates[0] ??
    null;
  const selectedOrganization =
    requestedOrganization ??
    organizations.find((organization) => organization.id === selectedWorkspace?.organizationId) ??
    organizations[0] ??
    null;

  return {
    organizations,
    workspaces,
    selectedOrganization,
    selectedWorkspace,
  };
}

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
