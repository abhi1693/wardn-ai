import { Plus } from "lucide-react";
import Link from "next/link";

import { AppShell } from "@/app/components/app-shell";
import { Button } from "@/components/ui/button";
import type { MCPServerInstallationListResponse } from "@/lib/api/generated/model";
import { backendJson } from "@/lib/api/server";
import {
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
  const data = await backendJson<MCPServerInstallationListResponse>(path);
  return data.installations;
}

type InstallListViewProps = {
  workspaceContext: WorkspaceContext;
};

export async function InstallListView({ workspaceContext }: InstallListViewProps) {
  const installations = await getInitialInstallations(workspaceContext);
  const basePath = workspaceInstallPath(workspaceContext);

  return (
    <AppShell
      active="install"
      actions={
        <Button asChild size="sm">
          <Link href={`${basePath}/new`}>
            <Plus className="size-4" />
            Add
          </Link>
        </Button>
      }
      eyebrow="MCP Runtime"
      title="MCP Servers"
      workspaceContext={workspaceContext}
    >
      <InstalledListClient
        basePath={basePath}
        initialInstallations={installations}
        organizationId={workspaceContext.selectedOrganization?.id ?? ""}
        workspaceId={workspaceContext.selectedWorkspace?.id ?? ""}
      />
    </AppShell>
  );
}
