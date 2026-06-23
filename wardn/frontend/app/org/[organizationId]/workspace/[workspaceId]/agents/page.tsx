import { Plus } from "lucide-react";
import Link from "next/link";

import { AppShell } from "@/app/components/app-shell";
import { AgentsClient } from "@/app/org/[organizationId]/agents/agents-client";
import { getWorkspaceAgents } from "@/app/org/[organizationId]/agents/data";
import { getLlmCredentials } from "@/app/org/[organizationId]/llm-credentials/data";
import { getOrganization } from "@/app/organizations/data";
import { Button } from "@/components/ui/button";
import { getWorkspaceContext } from "@/lib/workspace-context";

type WorkspaceAgentsPageProps = {
  params: Promise<{ organizationId: string; workspaceId: string }>;
};

export default async function WorkspaceAgentsPage({ params }: WorkspaceAgentsPageProps) {
  const { organizationId, workspaceId } = await params;
  const [workspaceContext, organization, agents, credentials] = await Promise.all([
    getWorkspaceContext({ organizationId, workspaceId }),
    getOrganization(organizationId),
    getWorkspaceAgents(organizationId, workspaceId),
    getLlmCredentials(organizationId),
  ]);

  if (!organization) {
    return null;
  }

  return (
    <AppShell
      active="workspace-agents"
      actions={
        <Button asChild size="sm">
          <Link href={`/org/${organization.id}/workspace/${workspaceId}/agents/new`}>
            <Plus className="size-4" />
            New agent
          </Link>
        </Button>
      }
      eyebrow="Workspace"
      title="Agents"
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
