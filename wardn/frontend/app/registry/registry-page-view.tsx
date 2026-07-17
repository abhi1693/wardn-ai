import { Plus } from "lucide-react";
import Link from "next/link";

import { AppShell } from "@/app/components/app-shell";
import { Button } from "@/components/ui/button";
import type {
  MCPRegistryServerListResponse,
  MCPServerInstallationListResponse,
} from "@/lib/api/generated/model";
import { backendJson } from "@/lib/api/server";
import {
  organizationMcpRegistryPath,
  type WorkspaceContext,
  workspaceMcpRegistryPath,
} from "@/lib/workspace-context";

import { CatalogListClient } from "./registry-list-client";

async function getInitialServers(context: WorkspaceContext) {
  const path = organizationMcpRegistryPath(context, "/servers?limit=50&version=latest");
  if (!path) {
    return { servers: [], metadata: { count: 0, nextCursor: "" } };
  }
  return backendJson<MCPRegistryServerListResponse>(path);
}

async function getInitialInstallations(context: WorkspaceContext) {
  const path = workspaceMcpRegistryPath(context, "/installed-servers");
  if (!path) {
    return [];
  }
  const data = await backendJson<MCPServerInstallationListResponse>(path);
  return data.installations;
}

type CatalogPageViewProps = {
  workspaceContext: WorkspaceContext;
};

export async function CatalogPageView({ workspaceContext }: CatalogPageViewProps) {
  const organizationId = workspaceContext.selectedOrganization?.id;
  const workspaceId = workspaceContext.selectedWorkspace?.id;
  const [serverList, installations] = await Promise.all([
    getInitialServers(workspaceContext),
    getInitialInstallations(workspaceContext),
  ]);

  return (
    <AppShell
      active="catalog"
      actions={
        <Button asChild size="sm">
          <Link href={organizationId ? `/org/${encodeURIComponent(organizationId)}/catalog/new` : "/org"}>
            <Plus className="size-4" />
            Add server
          </Link>
        </Button>
      }
      eyebrow="MCP Catalog"
      title="Catalog"
      workspaceContext={workspaceContext}
    >
      <CatalogListClient
        initialInstallations={installations}
        initialMetadata={serverList.metadata}
        initialServers={serverList.servers}
        organizationId={organizationId ?? ""}
        workspaceId={workspaceId ?? ""}
      />
    </AppShell>
  );
}
