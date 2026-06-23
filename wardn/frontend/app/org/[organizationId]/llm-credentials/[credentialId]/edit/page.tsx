import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { AppShell } from "@/app/components/app-shell";
import { getOrganization, getWorkspaces } from "@/app/organizations/data";
import { Button } from "@/components/ui/button";
import { getWorkspaceContext } from "@/lib/workspace-context";

import { CredentialForm } from "../../credential-form";
import { getCurrentUser } from "../../current-user";
import { getLlmCredentials } from "../../data";

type EditLlmCredentialPageProps = {
  params: Promise<{ organizationId: string; credentialId: string }>;
};

export default async function EditLlmCredentialPage({
  params,
}: EditLlmCredentialPageProps) {
  const { organizationId, credentialId } = await params;
  const [workspaceContext, organization, workspaces, credentials, currentUser] = await Promise.all([
    getWorkspaceContext({ organizationId }),
    getOrganization(organizationId),
    getWorkspaces(organizationId),
    getLlmCredentials(organizationId),
    getCurrentUser(),
  ]);
  const credential = credentials.find((entry) => entry.id === credentialId);

  if (!organization || !credential) {
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
      title="Edit Credential"
      workspaceContext={workspaceContext}
    >
      <CredentialForm
        credential={credential}
        currentUser={currentUser}
        organization={organization}
        workspaces={workspaces}
      />
    </AppShell>
  );
}
