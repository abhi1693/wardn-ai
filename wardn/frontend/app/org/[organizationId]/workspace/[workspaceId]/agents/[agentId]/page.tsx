import { ArrowLeft, Pencil } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { AppShell } from "@/app/components/app-shell";
import { AgentChatClient } from "@/app/org/[organizationId]/agents/[agentId]/agent-chat-client";
import { getWorkspaceAgents } from "@/app/org/[organizationId]/agents/data";
import { getOrganization } from "@/app/organizations/data";
import { Button } from "@/components/ui/button";
import { getWorkspaceContext } from "@/lib/workspace-context";

type WorkspaceAgentChatPageProps = {
  params: Promise<{ organizationId: string; workspaceId: string; agentId: string }>;
};

export default async function WorkspaceAgentChatPage({ params }: WorkspaceAgentChatPageProps) {
  const { organizationId, workspaceId, agentId } = await params;
  const [workspaceContext, organization, agents] = await Promise.all([
    getWorkspaceContext({ organizationId, workspaceId }),
    getOrganization(organizationId),
    getWorkspaceAgents(organizationId, workspaceId),
  ]);
  const agent = agents.find((entry) => entry.id === agentId);

  if (!organization || !agent) {
    notFound();
  }

  return (
    <AppShell
      active="workspace-agents"
      actions={
        <div className="flex gap-2">
          <Button asChild size="sm" variant="outline">
            <Link href={`/org/${organization.id}/workspace/${workspaceId}/agents`}>
              <ArrowLeft className="size-4" />
              Agents
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
      eyebrow="Agents"
      title={agent.name}
      workspaceContext={workspaceContext}
    >
      <AgentChatClient agent={agent} organization={organization} workspaceId={workspaceId} />
    </AppShell>
  );
}
