import { notFound } from "next/navigation";

import { AppShell } from "@/app/components/app-shell";
import { getSecretStores } from "@/app/organizations/data";
import type {
  MCPServerInstallationListResponse,
  MCPServerInstallationRead,
} from "@/lib/api/generated/model";
import { backendJson } from "@/lib/api/server";
import {
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
  const data = await backendJson<MCPServerInstallationListResponse>(path);
  return data.installations;
}

type EditInstallViewProps = {
  installationId: string;
  workspaceContext: WorkspaceContext;
};

export async function EditInstallView({ installationId, workspaceContext }: EditInstallViewProps) {
  const organizationId = workspaceContext.selectedOrganization?.id ?? "";
  const [installations, secretStores] = await Promise.all([
    getInitialInstallations(workspaceContext),
    organizationId ? getSecretStores(organizationId) : [],
  ]);
  const installation: MCPServerInstallationRead | undefined = installations.find(
    (item) => item.id === installationId
  );

  if (!installation) {
    notFound();
  }

  return (
    <AppShell
      active="install"
      eyebrow="MCP Runtime"
      title="Edit MCP server"
      workspaceContext={workspaceContext}
    >
      <InstallFormClient
        basePath={workspaceInstallPath(workspaceContext)}
        initialInstallation={installation}
        initialInstallations={installations}
        organizationId={organizationId}
        secretStores={secretStores}
        workspaceId={workspaceContext.selectedWorkspace?.id ?? ""}
      />
    </AppShell>
  );
}
