import { AppShell } from "@/app/components/app-shell";
import { getSecretStores } from "@/app/organizations/data";
import type {
  MCPRegistryServerListResponse,
  MCPServerInstallationListResponse,
} from "@/lib/api/generated/model";
import { backendJson } from "@/lib/api/server";
import {
  organizationMcpRegistryPath,
  type WorkspaceContext,
  workspaceInstallPath,
  workspaceMcpRegistryPath,
} from "@/lib/workspace-context";

import { InstallFormClient } from "./install-form-client";

const SERVER_PICKER_PAGE_SIZE = 10;

async function getInitialInstallations(context: WorkspaceContext) {
  const path = workspaceMcpRegistryPath(context, "/installed-servers");
  if (!path) {
    return [];
  }
  const data = await backendJson<MCPServerInstallationListResponse>(path);
  return data.installations;
}

async function getInitialServers(context: WorkspaceContext) {
  const path = organizationMcpRegistryPath(
    context,
    `/servers?limit=${SERVER_PICKER_PAGE_SIZE}&version=latest`
  );
  const emptyResponse: MCPRegistryServerListResponse = {
    servers: [],
    metadata: { count: 0, nextCursor: "" },
  };
  if (!path) {
    return emptyResponse;
  }
  return backendJson<MCPRegistryServerListResponse>(path);
}

async function getServer(context: WorkspaceContext, serverName: string, version: string) {
  if (!serverName) {
    return null;
  }

  const encodedName = serverName.split("/").map(encodeURIComponent).join("/");
  const path = organizationMcpRegistryPath(
    context,
    `/servers/${encodedName}/versions/${encodeURIComponent(version || "latest")}`
  );
  if (!path) {
    return null;
  }
  return backendJson<MCPRegistryServerListResponse["servers"][number]>(path);
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
  const organizationId = workspaceContext.selectedOrganization?.id ?? "";
  const [installations, serverList, selectedServer, secretStores] = await Promise.all([
    getInitialInstallations(workspaceContext),
    getInitialServers(workspaceContext),
    getServer(workspaceContext, serverName, version),
    organizationId ? getSecretStores(organizationId) : [],
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
        initialServerNextCursor={serverList.metadata.nextCursor ?? ""}
        initialServers={selectedServer ? [selectedServer, ...serverList.servers] : serverList.servers}
        organizationId={organizationId}
        secretStores={secretStores}
        workspaceId={workspaceContext.selectedWorkspace?.id ?? ""}
      />
    </AppShell>
  );
}
