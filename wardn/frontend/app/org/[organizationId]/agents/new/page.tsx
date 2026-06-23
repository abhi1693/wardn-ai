import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { AppShell } from "@/app/components/app-shell";
import { getOrganization, getWorkspaces } from "@/app/organizations/data";
import { Button } from "@/components/ui/button";
import { getWorkspaceContext } from "@/lib/workspace-context";

import { getLlmCredentials } from "../../llm-credentials/data";
import { AgentForm } from "../agent-form";

type NewAgentPageProps = {
  params: Promise<{ organizationId: string }>;
};

export default async function NewAgentPage({ params }: NewAgentPageProps) {
  const { organizationId } = await params;
  const [workspaceContext, organization, workspaces, credentials] = await Promise.all([
    getWorkspaceContext({ organizationId }),
    getOrganization(organizationId),
    getWorkspaces(organizationId),
    getLlmCredentials(organizationId),
  ]);

  if (!organization) {
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
      title="Create Agent"
      workspaceContext={workspaceContext}
    >
      <AgentForm
        credentials={credentials}
        organization={organization}
        workspaces={workspaces}
      />
    </AppShell>
  );
}
