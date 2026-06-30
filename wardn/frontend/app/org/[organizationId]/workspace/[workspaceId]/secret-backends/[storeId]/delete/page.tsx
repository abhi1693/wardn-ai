import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { AppShell } from "@/app/components/app-shell";
import {
  getOrganization,
  getSecretStore,
  getWorkspace,
} from "@/app/organizations/data";
import { SecretBackendDeleteClient } from "@/app/organizations/secret-backend-delete-client";
import { secretBackendsPath } from "@/app/organizations/secret-backends-paths";
import { Button } from "@/components/ui/button";
import { getWorkspaceContext } from "@/lib/workspace-context";

type DeleteWorkspaceSecretBackendPageProps = {
  params: Promise<{ organizationId: string; workspaceId: string; storeId: string }>;
};

export default async function DeleteWorkspaceSecretBackendPage({
  params,
}: DeleteWorkspaceSecretBackendPageProps) {
  const { organizationId, workspaceId, storeId } = await params;
  const [workspaceContext, organization, workspace, store] = await Promise.all([
    getWorkspaceContext({ organizationId, workspaceId }),
    getOrganization(organizationId),
    getWorkspace(organizationId, workspaceId),
    getSecretStore(organizationId, storeId),
  ]);

  if (!organization || !workspace || !store || store.workspaceId !== workspace.id) {
    notFound();
  }

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
      title="Delete Backend"
      workspaceContext={workspaceContext}
    >
      <div className="mx-auto max-w-2xl">
        <SecretBackendDeleteClient
          organizationId={organization.id}
          store={store}
          workspaceId={workspace.id}
        />
      </div>
    </AppShell>
  );
}
