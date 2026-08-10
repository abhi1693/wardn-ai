import { Plus } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { AppShell } from "@/components/templates/app-shell";
import { Button } from "@/components/atoms/button";
import { getWorkspaceContext } from "@/lib/workspace-context";

import { CredentialsClient } from "./credentials-client";
import { getLlmCredentials } from "./data";

type LlmCredentialsPageProps = {
  params: Promise<{ organizationId: string }>;
};

export default async function LlmCredentialsPage({ params }: LlmCredentialsPageProps) {
  const { organizationId } = await params;
  const [workspaceContext, credentials] = await Promise.all([
    getWorkspaceContext({ organizationId }),
    getLlmCredentials(organizationId),
  ]);
  const organization = workspaceContext.selectedOrganization;
  const workspaces = workspaceContext.workspaces;

  if (!organization) {
    notFound();
  }

  return (
    <AppShell
      active="llm-credentials"
      actions={
        <Button asChild size="sm">
          <Link href={`/org/${organization.id}/llm-credentials/new`}>
            <Plus className="size-4" />
            New credential
          </Link>
        </Button>
      }
      eyebrow="Organization"
      title="LLM Credentials"
      workspaceContext={workspaceContext}
    >
      <CredentialsClient
        credentials={credentials}
        organization={organization}
        workspaces={workspaces}
      />
    </AppShell>
  );
}
