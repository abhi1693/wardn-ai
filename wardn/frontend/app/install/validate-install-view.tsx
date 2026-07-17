import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { AppShell } from "@/app/components/app-shell";
import { Button } from "@/components/ui/button";
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

import { ValidateInstallClient } from "./validate-install-client";

async function getInitialInstallations(context: WorkspaceContext) {
  const path = workspaceMcpRegistryPath(context, "/installed-servers");
  if (!path) {
    return [];
  }
  const data = await backendJson<MCPServerInstallationListResponse>(path);
  return data.installations;
}

type ValidateInstallViewProps = {
  installationId: string;
  workspaceContext: WorkspaceContext;
};

export async function ValidateInstallView({
  installationId,
  workspaceContext,
}: ValidateInstallViewProps) {
  const installations = await getInitialInstallations(workspaceContext);
  const installation: MCPServerInstallationRead | undefined = installations.find(
    (item) => item.id === installationId
  );
  const installPath = workspaceInstallPath(workspaceContext);

  if (!installation) {
    notFound();
  }

  return (
    <AppShell
      active="install"
      actions={
        <Button asChild size="sm" variant="outline">
          <Link href={installPath}>
            <ArrowLeft className="size-4" />
            MCP Servers
          </Link>
        </Button>
      }
      eyebrow="MCP Runtime"
      title="Validate MCP server"
      workspaceContext={workspaceContext}
    >
      <ValidateInstallClient
        installation={installation}
        organizationId={workspaceContext.selectedOrganization?.id ?? ""}
        workspaceId={workspaceContext.selectedWorkspace?.id ?? ""}
      />
    </AppShell>
  );
}
