import { Settings } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { AppShell } from "@/app/components/app-shell";
import { AgentChatClient } from "@/app/org/[organizationId]/agents/[agentId]/agent-chat-client";
import { getLlmCredentials } from "@/app/org/[organizationId]/llm-credentials/data";
import { Button } from "@/components/ui/button";
import type { AgentConversationResponse } from "@/lib/api/generated/model";
import { backendJson } from "@/lib/api/server";
import { getWorkspaceContext } from "@/lib/workspace-context";

type WorkspaceConversationChatPageProps = {
  params: Promise<{ organizationId: string; workspaceId: string; conversationId: string }>;
};

async function getWorkspaceConversation(
  organizationId: string,
  workspaceId: string,
  conversationId: string
): Promise<AgentConversationResponse> {
  return backendJson<AgentConversationResponse>(
    `/api/v1/organizations/${encodeURIComponent(
      organizationId
    )}/workspaces/${encodeURIComponent(workspaceId)}/agents/conversations/${encodeURIComponent(
      conversationId
    )}`
  );
}

export default async function WorkspaceConversationChatPage({
  params,
}: WorkspaceConversationChatPageProps) {
  const { organizationId, workspaceId, conversationId } = await params;
  const [workspaceContext, credentials, conversation] = await Promise.all([
    getWorkspaceContext({ organizationId, workspaceId }),
    getLlmCredentials(organizationId),
    getWorkspaceConversation(organizationId, workspaceId, conversationId),
  ]);
  const organization = workspaceContext.selectedOrganization;

  if (!organization || !conversation) {
    notFound();
  }

  return (
    <AppShell
      active="workspace-chat"
      actions={
        <Button asChild size="sm" variant="outline">
          <Link href={`/org/${organization.id}/workspace/${workspaceId}/agents`}>
            <Settings className="size-4" />
            Manage agents
          </Link>
        </Button>
      }
      contentClassName="h-screen min-h-0 max-w-none px-0 pb-0 pt-16 max-lg:h-auto max-lg:pt-0 max-md:px-0 max-md:pb-0"
      contentInnerClassName="h-full space-y-0"
      eyebrow="Workspace"
      sectionClassName="max-lg:min-h-0"
      title="Chat"
      workspaceContext={workspaceContext}
    >
      <AgentChatClient
        agent={conversation.agent}
        conversation={conversation.conversation}
        credentials={credentials}
        initialMessages={conversation.messages}
        organization={organization}
        workspaceId={workspaceId}
      />
    </AppShell>
  );
}
