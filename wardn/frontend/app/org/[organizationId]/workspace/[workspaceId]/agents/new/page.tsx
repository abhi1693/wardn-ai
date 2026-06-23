import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { AppShell } from "@/app/components/app-shell";
import { getWorkspaceAgentAvailableTools } from "@/app/org/[organizationId]/agents/data";
import { AgentForm } from "@/app/org/[organizationId]/agents/agent-form";
import { getLlmCredentials } from "@/app/org/[organizationId]/llm-credentials/data";
import { getOrganization } from "@/app/organizations/data";
import { Button } from "@/components/ui/button";
import { getWorkspaceContext } from "@/lib/workspace-context";

type NewWorkspaceAgentPageProps = {
  params: Promise<{ organizationId: string; workspaceId: string }>;
};

export default async function NewWorkspaceAgentPage({ params }: NewWorkspaceAgentPageProps) {
  const { organizationId, workspaceId } = await params;
  const [workspaceContext, organization, credentials, availableTools] =
    await Promise.all([
      getWorkspaceContext({ organizationId, workspaceId }),
      getOrganization(organizationId),
      getLlmCredentials(organizationId),
      getWorkspaceAgentAvailableTools(organizationId, workspaceId),
    ]);

  if (!organization) {
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
      title="New Agent"
      workspaceContext={workspaceContext}
    >
      <AgentForm
        availableTools={availableTools}
        credentials={credentials}
        fixedWorkspaceId={workspaceId}
        organization={organization}
      />
    </AppShell>
  );
}
