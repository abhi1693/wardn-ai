import { Plus } from "lucide-react";
import Link from "next/link";

import { AppShell } from "@/app/components/app-shell";
import { Button } from "@/components/ui/button";
import type {
  MCPRegistryServerListResponse,
  MCPServerInstallationListResponse,
} from "@/lib/api/generated/model";
import {
  backendCookieHeader,
  backendPath,
  organizationMcpRegistryPath,
  type WorkspaceContext,
  workspaceMcpRegistryPath,
} from "@/lib/workspace-context";

import { RegistryListClient } from "./registry-list-client";

async function getInitialServers(context: WorkspaceContext) {
  const path = organizationMcpRegistryPath(context, "/servers?limit=50&version=latest");
  if (!path) {
    return { servers: [], metadata: { count: 0, nextCursor: "" } };
  }
  try {
    const cookie = await backendCookieHeader();
    const response = await fetch(backendPath(path), {
      cache: "no-store",
      headers: cookie ? { cookie } : {},
    });
    if (!response.ok) {
      return { servers: [], metadata: { count: 0, nextCursor: "" } };
    }
    return (await response.json()) as MCPRegistryServerListResponse;
  } catch {
    return { servers: [], metadata: { count: 0, nextCursor: "" } };
  }
}

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

type RegistryPageViewProps = {
  workspaceContext: WorkspaceContext;
};

export async function RegistryPageView({ workspaceContext }: RegistryPageViewProps) {
  const organizationId = workspaceContext.selectedOrganization?.id;
  const [serverList, installations] = await Promise.all([
    getInitialServers(workspaceContext),
    getInitialInstallations(workspaceContext),
  ]);

  return (
    <AppShell
      active="registry"
      actions={
        <Button asChild size="sm">
          <Link href={organizationId ? `/org/${encodeURIComponent(organizationId)}/registry/new` : "/org"}>
            <Plus className="size-4" />
            Add server
          </Link>
        </Button>
      }
      eyebrow="MCP Registry"
      title="Servers"
      workspaceContext={workspaceContext}
    >
      <RegistryListClient
        initialInstallations={installations}
        initialMetadata={serverList.metadata}
        initialServers={serverList.servers}
        organizationId={organizationId ?? ""}
      />
    </AppShell>
  );
}
