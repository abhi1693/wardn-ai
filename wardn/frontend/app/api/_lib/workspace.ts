import type { NextRequest } from "next/server";

import {
  selectedOrganizationCookie,
  selectedWorkspaceCookie,
} from "@/lib/workspace-types";

const backendUrl = process.env.WARDN_BACKEND_URL ?? "http://127.0.0.1:8000";

type Organization = {
  id: string;
};

type Workspace = {
  id: string;
  organizationId?: string;
};

function cookieHeader(request: Request) {
  return request.headers.get("cookie") ?? "";
}

function cookieValue(request: NextRequest | Request, name: string) {
  if ("cookies" in request) {
    return request.cookies.get(name)?.value ?? "";
  }

  const cookies = cookieHeader(request).split(";");
  for (const cookie of cookies) {
    const [rawName, ...rawValue] = cookie.trim().split("=");
    if (rawName === name) {
      return decodeURIComponent(rawValue.join("="));
    }
  }
  return "";
}

function routeWorkspaceContext(request: NextRequest | Request) {
  const referer = request.headers.get("referer");
  if (!referer) {
    return null;
  }
  try {
    const pathname = new URL(referer).pathname;
    const match = pathname.match(/^\/org\/([^/]+)\/workspace\/([^/]+)/);
    if (!match) {
      return null;
    }
    return {
      organizationId: decodeURIComponent(match[1] ?? ""),
      workspaceId: decodeURIComponent(match[2] ?? ""),
    };
  } catch {
    return null;
  }
}

async function fetchJson<T>(request: Request, path: string): Promise<T | null> {
  try {
    const response = await fetch(`${backendUrl}${path}`, {
      cache: "no-store",
      headers: {
        cookie: cookieHeader(request),
      },
    });
    if (!response.ok) {
      return null;
    }
    return (await response.json()) as T;
  } catch {
    return null;
  }
}

export async function selectedWorkspaceMcpPath(
  request: NextRequest | Request,
  suffix: string,
) {
  const routeContext = routeWorkspaceContext(request);
  const organizationsPayload = await fetchJson<{ organizations: Organization[] }>(
    request,
    "/api/v1/organizations"
  );
  const organizations = organizationsPayload?.organizations ?? [];
  const requestedOrganizationId =
    routeContext?.organizationId || cookieValue(request, selectedOrganizationCookie);
  const organization =
    organizations.find((item) => item.id === requestedOrganizationId) ??
    organizations[0] ??
    null;
  if (!organization) {
    return "";
  }

  const workspacesPayload = await fetchJson<{ workspaces: Workspace[] }>(
    request,
    `/api/v1/organizations/${encodeURIComponent(organization.id)}/workspaces`
  );
  const workspaces = workspacesPayload?.workspaces ?? [];
  const requestedWorkspaceId =
    routeContext?.workspaceId || cookieValue(request, selectedWorkspaceCookie);
  const workspace =
    workspaces.find((item) => item.id === requestedWorkspaceId) ??
    workspaces[0] ??
    null;
  if (!workspace) {
    return "";
  }

  return `${backendUrl}/api/v1/organizations/${encodeURIComponent(
    organization.id
  )}/workspaces/${encodeURIComponent(workspace.id)}/mcp${suffix}`;
}

export async function selectedOrganizationMcpRegistryPath(
  request: NextRequest | Request,
  suffix: string,
) {
  const routeContext = routeWorkspaceContext(request);
  const organizationsPayload = await fetchJson<{ organizations: Organization[] }>(
    request,
    "/api/v1/organizations"
  );
  const organizations = organizationsPayload?.organizations ?? [];
  const requestedOrganizationId =
    routeContext?.organizationId || cookieValue(request, selectedOrganizationCookie);
  const organization =
    organizations.find((item) => item.id === requestedOrganizationId) ??
    organizations[0] ??
    null;
  if (!organization) {
    return "";
  }

  return `${backendUrl}/api/v1/organizations/${encodeURIComponent(
    organization.id
  )}/mcp/registry${suffix}`;
}

export function backendContentHeaders(response: Response) {
  return {
    "content-type": response.headers.get("content-type") ?? "application/json",
  };
}
