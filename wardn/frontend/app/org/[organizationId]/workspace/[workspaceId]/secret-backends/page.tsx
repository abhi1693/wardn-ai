import { Plus } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { AppShell } from "@/app/components/app-shell";
import {
  getOrganization,
  getSecretStores,
  getWorkspace,
} from "@/app/organizations/data";
import { SecretBackendsClient } from "@/app/organizations/secret-backends-client";
import { newSecretBackendPath } from "@/app/organizations/secret-backends-paths";
import { Button } from "@/components/ui/button";
import { getWorkspaceContext } from "@/lib/workspace-context";

type WorkspaceSecretBackendsPageProps = {
  params: Promise<{ organizationId: string; workspaceId: string }>;
};

export default async function WorkspaceSecretBackendsPage({
  params,
}: WorkspaceSecretBackendsPageProps) {
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
  const workspaceStores = secretStores.filter((store) => store.workspaceId === workspace.id);
  const inheritedStore =
    secretStores.find((store) => !store.workspaceId && store.isActive) ??
    null;

  return (
    <AppShell
      active="workspace-secret-backends"
      actions={
        <Button asChild size="sm">
          <Link
            href={newSecretBackendPath({
              organizationId: organization.id,
              workspaceId: workspace.id,
            })}
          >
            <Plus className="size-4" />
            New backend
          </Link>
        </Button>
      }
      eyebrow="Workspace"
      title="Secret Backends"
      workspaceContext={workspaceContext}
    >
      <div className="mx-auto max-w-5xl">
        <SecretBackendsClient
          inheritedStore={inheritedStore}
          organizationId={organization.id}
          scopeLabel="Workspace"
          stores={workspaceStores}
          workspaceId={workspace.id}
        />
      </div>
    </AppShell>
  );
}
