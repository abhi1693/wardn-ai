import { notFound } from "next/navigation";

import { AppShell } from "@/app/components/app-shell";
import type { MCPRegistryServerResponse } from "@/lib/api/generated/model";
import {
  backendCookieHeader,
  backendPath,
  organizationMcpRegistryPath,
  type WorkspaceContext,
  workspaceInstallPath,
} from "@/lib/workspace-context";

import { ServerForm } from "./server-form";

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

type NewVersionPageViewProps = {
  createSuccessPath: string;
  serverName: string;
  version: string;
  workspaceContext: WorkspaceContext;
};

export async function NewVersionPageView({
  createSuccessPath,
  serverName,
  version,
  workspaceContext,
}: NewVersionPageViewProps) {
  const response = await getServer(workspaceContext, serverName, version);

  if (!response) {
    notFound();
  }

  return (
    <AppShell
      active="registry"
      eyebrow="MCP Registry"
      title="Add server version"
      workspaceContext={workspaceContext}
    >
      <ServerForm
        createSuccessPath={createSuccessPath}
        installBasePath={workspaceInstallPath(workspaceContext)}
        initialServer={response.server}
        mode="create"
      />
    </AppShell>
  );
}
