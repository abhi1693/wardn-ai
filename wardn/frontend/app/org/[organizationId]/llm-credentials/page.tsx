import { Plus } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { AppShell } from "@/app/components/app-shell";
import { getOrganization, getWorkspaces } from "@/app/organizations/data";
import { Button } from "@/components/ui/button";
import { getWorkspaceContext } from "@/lib/workspace-context";

import { CredentialsClient } from "./credentials-client";
import { getLlmCredentials } from "./data";

type LlmCredentialsPageProps = {
  params: Promise<{ organizationId: string }>;
};

export default async function LlmCredentialsPage({ params }: LlmCredentialsPageProps) {
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
