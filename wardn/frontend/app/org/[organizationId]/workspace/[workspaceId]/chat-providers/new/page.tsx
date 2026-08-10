import { notFound } from "next/navigation";

import { AppShell } from "@/components/templates/app-shell";
import { ChatProviderFormLoader } from "@/app/org/[organizationId]/workspace/[workspaceId]/chat-providers/_components/chat-provider-form-loader";
import type {
  ChatProviderConnectionListResponse,
  SecretStoreListResponse,
} from "@/lib/api/generated/model";
import { backendJson } from "@/lib/api/server";
import { getWorkspaceContext } from "@/lib/workspace-context";

type NewChatProviderPageProps = {
  params: Promise<{ organizationId: string; workspaceId: string }>;
};

async function getProviderPayload(organizationId: string, workspaceId: string) {
  return backendJson<ChatProviderConnectionListResponse>(
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

export default async function NewChatProviderPage({ params }: NewChatProviderPageProps) {
  const { organizationId, workspaceId } = await params;
  const [workspaceContext, providerPayload, secretStores] = await Promise.all([
    getWorkspaceContext({ organizationId, workspaceId }),
    getProviderPayload(organizationId, workspaceId),
    getSecretStores(organizationId, workspaceId),
  ]);
  const organization = workspaceContext.selectedOrganization;
  const workspace = workspaceContext.selectedWorkspace;

  if (!organization || !workspace) {
    notFound();
  }

  const basePath = `/org/${encodeURIComponent(organization.id)}/workspace/${encodeURIComponent(
    workspace.id
  )}/chat-providers`;

  return (
    <AppShell
      active="workspace-chat-providers"
      contentClassName="mx-0 max-w-none px-0"
      contentInnerClassName="space-y-0"
      eyebrow="Workspace"
      title="New Chat Provider"
      workspaceContext={workspaceContext}
    >
      <ChatProviderFormLoader
        basePath={basePath}
        defaultWhatsappBridgeBaseUrl={
          process.env.WARDN_CHAT_PROVIDER_WHATSAPP_BRIDGE_BASE_URL?.trim() ?? ""
        }
        mode="create"
        organizationId={organization.id}
        secretStores={secretStores}
        workspaceId={workspace.id}
        workspaceMembers={providerPayload.workspaceMembers ?? []}
      />
    </AppShell>
  );
}
