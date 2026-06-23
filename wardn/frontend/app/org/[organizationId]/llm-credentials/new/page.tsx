import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { AppShell } from "@/app/components/app-shell";
import { getOrganization, getWorkspaces } from "@/app/organizations/data";
import { Button } from "@/components/ui/button";
import { getWorkspaceContext } from "@/lib/workspace-context";

import { CredentialForm } from "../credential-form";
import { getCurrentUser } from "../current-user";

type NewLlmCredentialPageProps = {
  params: Promise<{ organizationId: string }>;
};

export default async function NewLlmCredentialPage({ params }: NewLlmCredentialPageProps) {
  const { organizationId } = await params;
  const [workspaceContext, organization, workspaces, currentUser] = await Promise.all([
    getWorkspaceContext({ organizationId }),
    getOrganization(organizationId),
    getWorkspaces(organizationId),
    getCurrentUser(),
  ]);

  if (!organization) {
    notFound();
  }

  return (
    <AppShell
      active="llm-credentials"
      actions={
        <Button asChild size="sm" variant="outline">
          <Link href={`/org/${organization.id}/llm-credentials`}>
            <ArrowLeft className="size-4" />
            Credentials
          </Link>
        </Button>
      }
      eyebrow="LLM Credentials"
      title="Create Credential"
      workspaceContext={workspaceContext}
    >
      <CredentialForm
        currentUser={currentUser}
        organization={organization}
        workspaces={workspaces}
      />
    </AppShell>
  );
}
