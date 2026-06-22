import { AppShell } from "@/app/components/app-shell";
import type {
  MCPRegistryServerListResponse,
  MCPServerInstallationListResponse,
} from "@/lib/api/generated/model";
import {
  backendCookieHeader,
  backendPath,
  organizationMcpRegistryPath,
  type WorkspaceContext,
  workspaceInstallPath,
  workspaceMcpRegistryPath,
} from "@/lib/workspace-context";

import { InstallFormClient } from "./install-form-client";

async function getInitialInstallations(context: WorkspaceContext) {
  const path = workspaceMcpRegistryPath(context, "/installed-servers");
  if (!path) {
    return [];
  }
  try {
    const cookie = await backendCookieHeader();
    const response = await fetch(backendPath(path), {
      cache: "no-store",
      headers: cookie ? { cookie } : {},
    });
    if (!response.ok) {
      return [];
    }
    const data = (await response.json()) as MCPServerInstallationListResponse;
    return data.installations;
  } catch {
    return [];
  }
}

async function getInitialServers(context: WorkspaceContext) {
  const path = organizationMcpRegistryPath(context, "/servers?limit=50&version=latest");
  if (!path) {
    return [];
  }
  try {
    const cookie = await backendCookieHeader();
    const response = await fetch(backendPath(path), {
      cache: "no-store",
      headers: cookie ? { cookie } : {},
    });
    if (!response.ok) {
      return [];
    }
    const data = (await response.json()) as MCPRegistryServerListResponse;
    return data.servers;
  } catch {
    return [];
  }
}

async function getServer(context: WorkspaceContext, serverName: string, version: string) {
  if (!serverName) {
    return null;
  }

  try {
    const encodedName = serverName.split("/").map(encodeURIComponent).join("/");
    const path = organizationMcpRegistryPath(
      context,
      `/servers/${encodedName}/versions/${encodeURIComponent(version || "latest")}`
    );
    if (!path) {
      return null;
    }
    const cookie = await backendCookieHeader();
    const response = await fetch(backendPath(path), {
      cache: "no-store",
      headers: cookie ? { cookie } : {},
    });
    if (!response.ok) {
      return null;
    }
    return (await response.json()) as MCPRegistryServerListResponse["servers"][number];
  } catch {
    return null;
  }
}

type NewInstallViewProps = {
  searchParams: {
    serverName?: string;
    version?: string;
  };
  workspaceContext: WorkspaceContext;
};

export async function NewInstallView({ searchParams, workspaceContext }: NewInstallViewProps) {
  const { serverName = "", version = "latest" } = searchParams;
  const [installations, servers, selectedServer] = await Promise.all([
    getInitialInstallations(workspaceContext),
    getInitialServers(workspaceContext),
    getServer(workspaceContext, serverName, version),
  ]);

  return (
    <AppShell
      active="install"
      eyebrow="MCP Runtime"
      title="Add MCP server"
      workspaceContext={workspaceContext}
    >
      <InstallFormClient
        basePath={workspaceInstallPath(workspaceContext)}
        initialInstallations={installations}
        initialSelectedServer={selectedServer}
        initialServers={selectedServer ? [selectedServer, ...servers] : servers}
      />
    </AppShell>
  );
}
