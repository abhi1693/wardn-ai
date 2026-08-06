import { notFound } from "next/navigation";

import { AppShell } from "@/app/components/app-shell";
import { ChatProvidersClient } from "@/app/org/[organizationId]/workspace/[workspaceId]/chat-providers/providers-client";
import type {
  ChatProviderConnectionListResponse,
  SecretHandleListResponse,
  SecretStoreListResponse,
} from "@/lib/api/generated/model";
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

async function getSecretStores(organizationId: string, workspaceId: string) {
  const payload = await backendJson<SecretStoreListResponse>(
    `/api/v1/organizations/${encodeURIComponent(
      organizationId
    )}/secrets/stores?workspaceId=${encodeURIComponent(workspaceId)}`
  );
  return payload.stores;
}

async function getSecretHandles(organizationId: string, workspaceId: string) {
  const payload = await backendJson<SecretHandleListResponse>(
    `/api/v1/organizations/${encodeURIComponent(
      organizationId
    )}/secrets/handles?workspaceId=${encodeURIComponent(workspaceId)}`
  );
  return payload.handles;
}

export default async function WorkspaceChatProvidersPage({
  params,
}: WorkspaceChatProvidersPageProps) {
  const { organizationId, workspaceId } = await params;
  const [workspaceContext, providerPayload, secretStores, secretHandles] = await Promise.all([
    getWorkspaceContext({ organizationId, workspaceId }),
    getProviderConnections(organizationId, workspaceId),
    getSecretStores(organizationId, workspaceId),
    getSecretHandles(organizationId, workspaceId),
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
        defaultWhatsappBridgeBaseUrl={
          process.env.WARDN_CHAT_PROVIDER_WHATSAPP_BRIDGE_BASE_URL?.trim() ?? ""
        }
        organizationId={organization.id}
        secretHandles={secretHandles}
        secretStores={secretStores}
        workspaceMembers={providerPayload.workspaceMembers ?? []}
        workspaceId={workspace.id}
      />
    </AppShell>
  );
}
