import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { AppShell } from "@/app/components/app-shell";
import {
  getOrganization,
  getSecretStore,
  getSecretStores,
  getWorkspace,
} from "@/app/organizations/data";
import { SecretBackendForm } from "@/app/organizations/secret-backend-form";
import { secretBackendsPath } from "@/app/organizations/secret-backends-paths";
import { Button } from "@/components/ui/button";
import { getWorkspaceContext } from "@/lib/workspace-context";

type EditWorkspaceSecretBackendPageProps = {
  params: Promise<{ organizationId: string; workspaceId: string; storeId: string }>;
};

export default async function EditWorkspaceSecretBackendPage({
  params,
}: EditWorkspaceSecretBackendPageProps) {
  const { organizationId, workspaceId, storeId } = await params;
  const [workspaceContext, organization, workspace, store, secretStores] =
    await Promise.all([
      getWorkspaceContext({ organizationId, workspaceId }),
      getOrganization(organizationId),
      getWorkspace(organizationId, workspaceId),
      getSecretStore(organizationId, storeId),
      getSecretStores(organizationId, workspaceId),
    ]);

  if (!organization || !workspace || !store || store.workspaceId !== workspace.id) {
    notFound();
  }

  const inheritedStore =
    secretStores.find((entry) => !entry.workspaceId && entry.isActive) ??
    null;
  const listPath = secretBackendsPath({
    organizationId: organization.id,
    workspaceId: workspace.id,
  });

  return (
    <AppShell
      active="workspace-secret-backends"
      actions={
        <Button asChild size="sm" variant="outline">
          <Link href={listPath}>
            <ArrowLeft className="size-4" />
            Backends
          </Link>
        </Button>
      }
      eyebrow="Workspace Secret Backends"
      title="Edit Backend"
      workspaceContext={workspaceContext}
    >
      <div className="mx-auto max-w-3xl">
        <SecretBackendForm
          inheritedStore={inheritedStore}
          mode="edit"
          organizationId={organization.id}
          store={store}
          workspaceId={workspace.id}
        />
      </div>
    </AppShell>
  );
}
