import { notFound } from "next/navigation";

import { AppShell } from "@/app/components/app-shell";
import { AgentsClient } from "@/app/org/[organizationId]/agents/agents-client";
import { getWorkspaceAgents } from "@/app/org/[organizationId]/agents/data";
import { getLlmCredentials } from "@/app/org/[organizationId]/llm-credentials/data";
import { getWorkspaceContext } from "@/lib/workspace-context";

type WorkspaceAgentsPageProps = {
  params: Promise<{ organizationId: string; workspaceId: string }>;
};

export default async function WorkspaceAgentsPage({ params }: WorkspaceAgentsPageProps) {
  const { organizationId, workspaceId } = await params;
  const [workspaceContext, agents, credentials] = await Promise.all([
    getWorkspaceContext({ organizationId, workspaceId }),
    getWorkspaceAgents(organizationId, workspaceId),
    getLlmCredentials(organizationId),
  ]);
  const organization = workspaceContext.selectedOrganization;

  if (!organization) {
    notFound();
  }

  return (
    <AppShell
      active="workspace-agents"
      eyebrow="Workspace"
      title="Manage Agents"
      workspaceContext={workspaceContext}
    >
      <AgentsClient
        agents={agents}
        credentials={credentials}
        organization={organization}
        workspaceId={workspaceId}
      />
    </AppShell>
  );
}
