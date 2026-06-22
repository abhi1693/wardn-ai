import { notFound } from "next/navigation";

import { AppShell } from "@/app/components/app-shell";
import type {
  MCPServerInstallationListResponse,
  MCPServerInstallationRead,
} from "@/lib/api/generated/model";
import {
  backendCookieHeader,
  backendPath,
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

type EditInstallViewProps = {
  installationId: string;
  workspaceContext: WorkspaceContext;
};

export async function EditInstallView({ installationId, workspaceContext }: EditInstallViewProps) {
  const installations = await getInitialInstallations(workspaceContext);
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
      />
    </AppShell>
  );
}
