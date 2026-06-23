import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { AppShell } from "@/app/components/app-shell";
import { getOrganization, getWorkspaces } from "@/app/organizations/data";
import { Button } from "@/components/ui/button";
import { getWorkspaceContext } from "@/lib/workspace-context";

import { getLlmCredentials } from "../../../llm-credentials/data";
import { AgentForm } from "../../agent-form";
import { getAgents } from "../../data";

type EditAgentPageProps = {
  params: Promise<{ organizationId: string; agentId: string }>;
};

export default async function EditAgentPage({ params }: EditAgentPageProps) {
  const { organizationId, agentId } = await params;
  const [workspaceContext, organization, workspaces, agents, credentials] = await Promise.all([
    getWorkspaceContext({ organizationId }),
    getOrganization(organizationId),
    getWorkspaces(organizationId),
    getAgents(organizationId),
    getLlmCredentials(organizationId),
  ]);
  const agent = agents.find((entry) => entry.id === agentId);

  if (!organization || !agent) {
    notFound();
  }

  return (
    <AppShell
      active="agents"
      actions={
        <Button asChild size="sm" variant="outline">
          <Link href={`/org/${organization.id}/agents`}>
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
        credentials={credentials}
        organization={organization}
        workspaces={workspaces}
      />
    </AppShell>
  );
}
