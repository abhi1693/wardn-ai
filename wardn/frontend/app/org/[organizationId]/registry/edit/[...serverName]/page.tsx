import { notFound } from "next/navigation";

import { AppShell } from "@/app/components/app-shell";
import type { MCPRegistryServerResponse } from "@/lib/api/generated/model";
import {
  backendCookieHeader,
  backendPath,
  getWorkspaceContext,
  organizationMcpRegistryPath,
  type WorkspaceContext,
  workspaceInstallPath,
} from "@/lib/workspace-context";

import { ServerForm } from "@/app/registry/server-form";

type EditRegistryServerPageProps = {
  params: Promise<{
    organizationId: string;
    serverName: string[];
  }>;
  searchParams: Promise<{
    version?: string;
  }>;
};

async function getServer(context: WorkspaceContext, serverName: string, version: string) {
  const encodedName = serverName.split("/").map(encodeURIComponent).join("/");
  const path = organizationMcpRegistryPath(
    context,
    `/servers/${encodedName}/versions/${encodeURIComponent(version)}`
  );
  if (!path) {
    return null;
  }
  const cookie = await backendCookieHeader();
  const response = await fetch(backendPath(path), {
    cache: "no-store",
    headers: cookie ? { cookie } : {},
  });
  if (response.status === 404) {
    notFound();
  }
  if (!response.ok) {
    return null;
  }
  return (await response.json()) as MCPRegistryServerResponse;
}

export default async function EditRegistryServerPage({
  params,
  searchParams,
}: EditRegistryServerPageProps) {
  const { organizationId, serverName } = await params;
  const { version } = await searchParams;
  const decodedName = serverName.map(decodeURIComponent).join("/");
  const selectedVersion = version || "latest";
  const workspaceContext = await getWorkspaceContext({ organizationId });
  const response = await getServer(workspaceContext, decodedName, selectedVersion);

  if (!response) {
    notFound();
  }

  return (
    <AppShell
      active="registry"
      eyebrow="MCP Registry"
      title="Edit server"
      workspaceContext={workspaceContext}
    >
      <ServerForm
        installBasePath={workspaceInstallPath(workspaceContext)}
        initialServer={response.server}
        editSuccessPath={`/org/${encodeURIComponent(organizationId)}/registry`}
        mode="edit"
      />
    </AppShell>
  );
}
