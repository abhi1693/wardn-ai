import { Plus } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { AppShell } from "@/app/components/app-shell";
import { getOrganization, getWorkspaces } from "@/app/organizations/data";
import { Button } from "@/components/ui/button";
import { getWorkspaceContext } from "@/lib/workspace-context";

import { getLlmCredentials } from "../llm-credentials/data";
import { AgentsClient } from "./agents-client";
import { getAgents } from "./data";

type AgentsPageProps = {
  params: Promise<{ organizationId: string }>;
};

export default async function AgentsPage({ params }: AgentsPageProps) {
  const { organizationId } = await params;
  const [workspaceContext, organization, workspaces, agents, credentials] = await Promise.all([
    getWorkspaceContext({ organizationId }),
    getOrganization(organizationId),
    getWorkspaces(organizationId),
    getAgents(organizationId),
    getLlmCredentials(organizationId),
  ]);

  if (!organization) {
    notFound();
  }

  return (
    <AppShell
      active="agents"
      actions={
        <Button asChild size="sm">
          <Link href={`/org/${organization.id}/agents/new`}>
            <Plus className="size-4" />
            New agent
          </Link>
        </Button>
      }
      eyebrow="Organization"
      title="Agents"
      workspaceContext={workspaceContext}
    >
      <AgentsClient
        agents={agents}
        credentials={credentials}
        organization={organization}
        workspaces={workspaces}
      />
    </AppShell>
  );
}
