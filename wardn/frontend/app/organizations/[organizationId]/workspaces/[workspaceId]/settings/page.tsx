import { notFound } from "next/navigation";

import { AppShell } from "@/components/templates/app-shell";

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
      title="Settings"
      workspaceContext={workspaceContext}
    >
      <div className="space-y-6">
        <section className="space-y-3">
          <div>
            <h2 className="text-base font-semibold">Workspace Profile</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Edit the workspace name, description, and lifecycle status.
            </p>
          </div>
          <WorkspaceForm
            initialWorkspace={workspace}
            mode="edit"
            organizationId={organization.id}
          />
        </section>
      </div>
    </AppShell>
  );
}
