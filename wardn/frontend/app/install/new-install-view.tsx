import { AppShell } from "@/components/templates/app-shell";
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
import { SERVER_PICKER_PAGE_SIZE } from "./install-form-domain";

async function getInitialInstallations(context: WorkspaceContext) {
  const path = workspaceMcpRegistryPath(context, "/installed-servers");
  const emptyResponse: MCPServerInstallationListResponse = {
    installations: [],
    metadata: { count: 0, nextCursor: "" },
    packageRuntimeProvider: "local",
  };
  if (!path) {
    return emptyResponse;
  }
  return backendJson<MCPServerInstallationListResponse>(path);
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
  const [installationsData, serverList, selectedServer, secretStores] = await Promise.all([
    getInitialInstallations(workspaceContext),
    getInitialServers(workspaceContext),
    getServer(workspaceContext, serverName, version),
    organizationId ? getSecretStores(organizationId) : [],
  ]);
  const installations = installationsData.installations;

  return (
    <AppShell
      active="install"
      eyebrow="Connections"
      title="Add Connection"
      workspaceContext={workspaceContext}
    >
      <InstallFormClient
        basePath={workspaceInstallPath(workspaceContext)}
        initialInstallations={installations}
        initialSelectedServer={selectedServer}
        initialServerNextCursor={serverList.metadata.nextCursor ?? ""}
        initialServers={selectedServer ? [selectedServer, ...serverList.servers] : serverList.servers}
        organizationId={organizationId}
        packageRuntimeProvider={installationsData.packageRuntimeProvider}
        secretStores={secretStores}
        workspaceId={workspaceContext.selectedWorkspace?.id ?? ""}
      />
    </AppShell>
  );
}
