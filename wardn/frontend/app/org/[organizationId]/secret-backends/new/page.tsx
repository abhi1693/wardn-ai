import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { AppShell } from "@/app/components/app-shell";
import { getOrganization } from "@/app/organizations/data";
import { SecretBackendForm } from "@/app/organizations/secret-backend-form";
import { secretBackendsPath } from "@/app/organizations/secret-backends-paths";
import { Button } from "@/components/ui/button";
import { getWorkspaceContext } from "@/lib/workspace-context";

type NewSecretBackendPageProps = {
  params: Promise<{ organizationId: string }>;
};

export default async function NewSecretBackendPage({ params }: NewSecretBackendPageProps) {
  const { organizationId } = await params;
  const [workspaceContext, organization] = await Promise.all([
    getWorkspaceContext({ organizationId }),
    getOrganization(organizationId),
  ]);

  if (!organization) {
    notFound();
  }

  const listPath = secretBackendsPath({ organizationId: organization.id });

  return (
    <AppShell
      active="secret-backends"
      actions={
        <Button asChild size="sm" variant="outline">
          <Link href={listPath}>
            <ArrowLeft className="size-4" />
            Backends
          </Link>
        </Button>
      }
      eyebrow="Secret Backends"
      title="Create Backend"
      workspaceContext={workspaceContext}
    >
      <div className="mx-auto max-w-3xl">
        <SecretBackendForm mode="create" organizationId={organization.id} />
      </div>
    </AppShell>
  );
}
