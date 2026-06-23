import { ArrowLeft, Pencil } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { AppShell } from "@/app/components/app-shell";
import { getOrganization } from "@/app/organizations/data";
import { Button } from "@/components/ui/button";
import { getWorkspaceContext } from "@/lib/workspace-context";

import { getAgents } from "../data";
import { AgentChatClient } from "./agent-chat-client";

type AgentChatPageProps = {
  params: Promise<{ organizationId: string; agentId: string }>;
};

export default async function AgentChatPage({ params }: AgentChatPageProps) {
  const { organizationId, agentId } = await params;
  const [workspaceContext, organization, agents] = await Promise.all([
    getWorkspaceContext({ organizationId }),
    getOrganization(organizationId),
    getAgents(organizationId),
  ]);
  const agent = agents.find((entry) => entry.id === agentId);

  if (!organization || !agent) {
    notFound();
  }

  return (
    <AppShell
      active="agents"
      actions={
        <div className="flex gap-2">
          <Button asChild size="sm" variant="outline">
            <Link href={`/org/${organization.id}/agents`}>
              <ArrowLeft className="size-4" />
              Agents
            </Link>
          </Button>
          <Button asChild size="sm" variant="outline">
            <Link href={`/org/${organization.id}/agents/${agent.id}/edit`}>
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
      <AgentChatClient agent={agent} organization={organization} />
    </AppShell>
  );
}
