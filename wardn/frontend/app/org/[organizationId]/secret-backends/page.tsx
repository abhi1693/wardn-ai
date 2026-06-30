import { Plus } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { AppShell } from "@/app/components/app-shell";
import { getOrganization, getSecretStores } from "@/app/organizations/data";
import { SecretBackendsClient } from "@/app/organizations/secret-backends-client";
import { newSecretBackendPath } from "@/app/organizations/secret-backends-paths";
import { Button } from "@/components/ui/button";
import { getWorkspaceContext } from "@/lib/workspace-context";

type SecretBackendsPageProps = {
  params: Promise<{ organizationId: string }>;
};

export default async function SecretBackendsPage({ params }: SecretBackendsPageProps) {
  const { organizationId } = await params;
  const [workspaceContext, organization, secretStores] = await Promise.all([
    getWorkspaceContext({ organizationId }),
    getOrganization(organizationId),
    getSecretStores(organizationId),
  ]);

  if (!organization) {
    notFound();
  }
  const organizationStores = secretStores.filter((store) => !store.workspaceId);

  return (
    <AppShell
      active="secret-backends"
      actions={
        <Button asChild size="sm">
          <Link href={newSecretBackendPath({ organizationId: organization.id })}>
            <Plus className="size-4" />
            New backend
          </Link>
        </Button>
      }
      eyebrow="Organization"
      title="Secret Backends"
      workspaceContext={workspaceContext}
    >
      <div className="mx-auto max-w-5xl space-y-8">
        <SecretBackendsClient
          organizationId={organization.id}
          scopeLabel="Organization"
          stores={organizationStores}
        />
      </div>
    </AppShell>
  );
}
