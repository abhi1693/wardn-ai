import { ArrowLeft, Pencil } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { AppShell } from "@/app/components/app-shell";
import { AgentChatClient } from "@/app/org/[organizationId]/agents/[agentId]/agent-chat-client";
import { getWorkspaceAgents } from "@/app/org/[organizationId]/agents/data";
import { getLlmCredentials } from "@/app/org/[organizationId]/llm-credentials/data";
import { Button } from "@/components/ui/button";
import { getWorkspaceContext } from "@/lib/workspace-context";

type WorkspaceAgentChatPageProps = {
  params: Promise<{ organizationId: string; workspaceId: string; agentId: string }>;
};

export default async function WorkspaceAgentChatPage({ params }: WorkspaceAgentChatPageProps) {
  const { organizationId, workspaceId, agentId } = await params;
  const [workspaceContext, agents, credentials] = await Promise.all([
    getWorkspaceContext({ organizationId, workspaceId }),
    getWorkspaceAgents(organizationId, workspaceId),
    getLlmCredentials(organizationId),
  ]);
  const organization = workspaceContext.selectedOrganization;
  const agent = agents.find((entry) => entry.id === agentId);

  if (!organization || !agent) {
    notFound();
  }

  return (
    <AppShell
      active="workspace-chat"
      actions={
        <div className="flex gap-2">
          <Button asChild size="sm" variant="outline">
            <Link href={`/org/${organization.id}/workspace/${workspaceId}/chat`}>
              <ArrowLeft className="size-4" />
              Chat
            </Link>
          </Button>
          <Button asChild size="sm" variant="outline">
            <Link
              href={`/org/${organization.id}/workspace/${workspaceId}/agents/${agent.id}/edit`}
            >
              <Pencil className="size-4" />
              Edit
            </Link>
          </Button>
        </div>
      }
      contentClassName="h-screen min-h-0 max-w-none px-0 pb-0 pt-16 max-lg:h-auto max-lg:pt-0 max-md:px-0 max-md:pb-0"
      contentInnerClassName="h-full space-y-0"
      eyebrow="Chat"
      sectionClassName="max-lg:min-h-0"
      title={agent.name}
      workspaceContext={workspaceContext}
    >
      <AgentChatClient
        agent={agent}
        credentials={credentials}
        organization={organization}
        workspaceId={workspaceId}
      />
    </AppShell>
  );
}
