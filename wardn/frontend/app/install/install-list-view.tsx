import { AppShell } from "@/app/components/app-shell";
import type { MCPServerInstallationListResponse } from "@/lib/api/generated/model";
import {
  backendCookieHeader,
  backendPath,
  type WorkspaceContext,
  workspaceInstallPath,
  workspaceMcpRegistryPath,
} from "@/lib/workspace-context";

import { InstalledListClient } from "./installed-list-client";

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

type InstallListViewProps = {
  workspaceContext: WorkspaceContext;
};

export async function InstallListView({ workspaceContext }: InstallListViewProps) {
  const installations = await getInitialInstallations(workspaceContext);

  return (
    <AppShell
      active="install"
      eyebrow="MCP Runtime"
      title="Install"
      workspaceContext={workspaceContext}
    >
      <InstalledListClient
        basePath={workspaceInstallPath(workspaceContext)}
        initialInstallations={installations}
        organizationId={workspaceContext.selectedOrganization?.id ?? ""}
      />
    </AppShell>
  );
}
