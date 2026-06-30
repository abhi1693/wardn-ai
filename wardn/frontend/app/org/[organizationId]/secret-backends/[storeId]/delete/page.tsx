import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { AppShell } from "@/app/components/app-shell";
import { getOrganization, getSecretStore } from "@/app/organizations/data";
import { SecretBackendDeleteClient } from "@/app/organizations/secret-backend-delete-client";
import { secretBackendsPath } from "@/app/organizations/secret-backends-paths";
import { Button } from "@/components/ui/button";
import { getWorkspaceContext } from "@/lib/workspace-context";

type DeleteSecretBackendPageProps = {
  params: Promise<{ organizationId: string; storeId: string }>;
};

export default async function DeleteSecretBackendPage({
  params,
}: DeleteSecretBackendPageProps) {
  const { organizationId, storeId } = await params;
  const [workspaceContext, organization, store] = await Promise.all([
    getWorkspaceContext({ organizationId }),
    getOrganization(organizationId),
    getSecretStore(organizationId, storeId),
  ]);

  if (!organization || !store || store.workspaceId) {
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
      title="Delete Backend"
      workspaceContext={workspaceContext}
    >
      <div className="mx-auto max-w-2xl">
        <SecretBackendDeleteClient organizationId={organization.id} store={store} />
      </div>
    </AppShell>
  );
}
