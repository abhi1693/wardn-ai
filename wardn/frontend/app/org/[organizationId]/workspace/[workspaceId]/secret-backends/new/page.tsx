import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { AppShell } from "@/app/components/app-shell";
import {
  getOrganization,
  getSecretStores,
  getWorkspace,
} from "@/app/organizations/data";
import { SecretBackendForm } from "@/app/organizations/secret-backend-form";
import { secretBackendsPath } from "@/app/organizations/secret-backends-paths";
import { Button } from "@/components/ui/button";
import { getWorkspaceContext } from "@/lib/workspace-context";

type NewWorkspaceSecretBackendPageProps = {
  params: Promise<{ organizationId: string; workspaceId: string }>;
};

export default async function NewWorkspaceSecretBackendPage({
  params,
}: NewWorkspaceSecretBackendPageProps) {
  const { organizationId, workspaceId } = await params;
  const [workspaceContext, organization, workspace, secretStores] = await Promise.all([
    getWorkspaceContext({ organizationId, workspaceId }),
    getOrganization(organizationId),
    getWorkspace(organizationId, workspaceId),
    getSecretStores(organizationId, workspaceId),
  ]);

  if (!organization || !workspace) {
    notFound();
  }

  const inheritedStore =
    secretStores.find((store) => !store.workspaceId && store.isActive) ??
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
      title="Create Backend"
      workspaceContext={workspaceContext}
    >
      <div className="mx-auto max-w-3xl">
        <SecretBackendForm
          inheritedStore={inheritedStore}
          mode="create"
          organizationId={organization.id}
          workspaceId={workspace.id}
        />
      </div>
    </AppShell>
  );
}
