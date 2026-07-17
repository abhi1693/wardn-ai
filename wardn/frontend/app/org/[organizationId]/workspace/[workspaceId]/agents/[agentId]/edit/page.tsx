import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { AppShell } from "@/app/components/app-shell";
import { AgentForm } from "@/app/org/[organizationId]/agents/agent-form";
import {
  getWorkspaceAgentAvailableTools,
  getWorkspaceAgentTools,
  getWorkspaceAgents,
} from "@/app/org/[organizationId]/agents/data";
import { getLlmCredentials } from "@/app/org/[organizationId]/llm-credentials/data";
import { Button } from "@/components/ui/button";
import { getWorkspaceContext } from "@/lib/workspace-context";

type EditWorkspaceAgentPageProps = {
  params: Promise<{ organizationId: string; workspaceId: string; agentId: string }>;
};

export default async function EditWorkspaceAgentPage({ params }: EditWorkspaceAgentPageProps) {
  const { organizationId, workspaceId, agentId } = await params;
  const [
    workspaceContext,
    agents,
    credentials,
    availableTools,
    assignedTools,
  ] = await Promise.all([
    getWorkspaceContext({ organizationId, workspaceId }),
    getWorkspaceAgents(organizationId, workspaceId),
    getLlmCredentials(organizationId),
    getWorkspaceAgentAvailableTools(organizationId, workspaceId),
    getWorkspaceAgentTools(organizationId, workspaceId, agentId),
  ]);
  const organization = workspaceContext.selectedOrganization;
  const agent = agents.find((entry) => entry.id === agentId);

  if (!organization || !agent) {
    notFound();
  }

  return (
    <AppShell
      active="workspace-agents"
      actions={
        <Button asChild size="sm" variant="outline">
          <Link href={`/org/${organization.id}/workspace/${workspaceId}/agents`}>
            <ArrowLeft className="size-4" />
            Agents
          </Link>
        </Button>
      }
      eyebrow="Agents"
      title="Edit Agent"
      workspaceContext={workspaceContext}
    >
      <AgentForm
        agent={agent}
        assignedServerAssignments={assignedTools.servers}
        availableServers={availableTools.servers}
        availableTools={availableTools.tools}
        credentials={credentials}
        fixedWorkspaceId={workspaceId}
        organization={organization}
      />
    </AppShell>
  );
}
