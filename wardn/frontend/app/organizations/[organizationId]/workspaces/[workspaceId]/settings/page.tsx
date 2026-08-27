import { notFound } from "next/navigation";

import { AppShell } from "@/components/templates/app-shell";

import { getWorkspaceContext } from "../../../../data";
import { WorkspaceForm } from "../../../../workspace-form";
import { DeleteWorkspaceDialog } from "../../../../delete-workspace-dialog";

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
  const canDelete =
    workspace.currentUserRole === "owner" || workspace.currentUserRole === "admin";
  const isDefaultWorkspace = organization.slug === "default" && workspace.slug === "default";

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
        {canDelete ? (
          <section className="rounded-md border border-destructive/30 bg-destructive/5 p-4">
            <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <h2 className="text-base font-semibold">Danger zone</h2>
                <p className="mt-1 text-sm text-muted-foreground">
                  Permanently delete this workspace after removing installed MCP servers and
                  managed-secret connections.
                </p>
              </div>
              <DeleteWorkspaceDialog
                isDefaultWorkspace={isDefaultWorkspace}
                organizationId={organization.id}
                replacementWorkspaces={workspaceContext.workspaces}
                workspace={workspace}
              />
            </div>
          </section>
        ) : null}
      </div>
    </AppShell>
  );
}
