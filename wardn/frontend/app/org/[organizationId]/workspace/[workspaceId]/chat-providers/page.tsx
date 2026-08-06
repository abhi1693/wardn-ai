import { notFound } from "next/navigation";

import { AppShell } from "@/app/components/app-shell";
import { ChatProvidersClient } from "@/app/org/[organizationId]/workspace/[workspaceId]/chat-providers/providers-client";
import type { ChatProviderConnectionListResponse } from "@/lib/api/generated/model";
import { backendJson } from "@/lib/api/server";
import { getWorkspaceContext } from "@/lib/workspace-context";

type WorkspaceChatProvidersPageProps = {
  params: Promise<{ organizationId: string; workspaceId: string }>;
};

async function getProviderConnections(organizationId: string, workspaceId: string) {
  return await backendJson<ChatProviderConnectionListResponse>(
    `/api/v1/organizations/${encodeURIComponent(
      organizationId
    )}/workspaces/${encodeURIComponent(workspaceId)}/chat-providers`
  );
}

export default async function WorkspaceChatProvidersPage({
  params,
}: WorkspaceChatProvidersPageProps) {
  const { organizationId, workspaceId } = await params;
  const [workspaceContext, providerPayload] = await Promise.all([
    getWorkspaceContext({ organizationId, workspaceId }),
    getProviderConnections(organizationId, workspaceId),
  ]);
  const organization = workspaceContext.selectedOrganization;
  const workspace = workspaceContext.selectedWorkspace;

  if (!organization || !workspace) {
    notFound();
  }

  return (
    <AppShell
      active="workspace-chat-providers"
      eyebrow="Workspace"
      title="Chat Providers"
      workspaceContext={workspaceContext}
    >
      <ChatProvidersClient
        connections={providerPayload.connections}
        organizationId={organization.id}
        workspaceId={workspace.id}
      />
    </AppShell>
  );
}
