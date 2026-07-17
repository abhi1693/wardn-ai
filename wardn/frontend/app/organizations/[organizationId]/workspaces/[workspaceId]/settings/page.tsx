import { notFound } from "next/navigation";

import { AppShell } from "@/app/components/app-shell";

import { getWorkspaceContext } from "../../../../data";
import { WorkspaceForm } from "../../../../workspace-form";

type WorkspaceSettingsPageProps = {
  params: Promise<{ organizationId: string; workspaceId: string }>;
};

export default async function WorkspaceSettingsPage({ params }: WorkspaceSettingsPageProps) {
  const { organizationId, workspaceId } = await params;
  const workspaceContext = await getWorkspaceContext({ organizationId, workspaceId });
  const organization = workspaceContext.selectedOrganization;
  const workspace = workspaceContext.selectedWorkspace;
  if (!organization || !workspace) {
    notFound();
  }

  return (
    <AppShell
      active="workspace-settings"
      eyebrow="Workspace"
      title={`${workspace.name} settings`}
      workspaceContext={workspaceContext}
    >
      <WorkspaceForm
        initialWorkspace={workspace}
        mode="edit"
        organizationId={organization.id}
      />
    </AppShell>
  );
}
