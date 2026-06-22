import { Boxes, Plus, Settings } from "lucide-react";
import Link from "next/link";

import { AppShell } from "@/app/components/app-shell";
import { OpenWorkspaceButton } from "@/app/components/open-workspace-button";
import { Button } from "@/components/ui/button";
import { getWorkspaceContext } from "@/lib/workspace-context";

export default async function Dashboard() {
  const workspaceContext = await getWorkspaceContext();
  const organization = workspaceContext.selectedOrganization;
  const workspaces = workspaceContext.workspaces.filter(
    (workspace) => workspace.organizationId === organization?.id
  );

  return (
    <AppShell
      active="dashboard"
      actions={!organization ? (
          <Button asChild size="sm">
            <Link href="/organizations/new">
              <Plus className="size-4" />
              Add organization
            </Link>
          </Button>
        ) : undefined}
      eyebrow="Organization"
      title="Overview"
      workspaceContext={workspaceContext}
    >
      {organization ? (
        <section id="workspaces">
          <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
            <Link
              className="flex min-h-48 items-center justify-center rounded-md border border-dashed bg-card text-sm font-medium text-muted-foreground transition-colors hover:border-foreground/40 hover:text-foreground"
              href={`/organizations/${organization.id}/workspaces/new`}
            >
              <Plus className="size-4" />
              <span className="ml-2">Create workspace</span>
            </Link>

            {workspaces.map((workspace) => (
              <div
                className="group flex min-h-48 flex-col rounded-md border bg-card transition-shadow hover:shadow-sm"
                key={workspace.id}
              >
                <div className="border-b px-4 py-3">
                  <div className="flex size-9 items-center justify-center rounded-md border bg-background text-muted-foreground">
                    <Boxes className="size-4" />
                  </div>
                </div>

                <div className="flex flex-1 flex-col px-4 py-4">
                  <div className="mt-auto">
                    <h2 className="text-base font-semibold">{workspace.name}</h2>
                    <div className="mt-1 text-sm text-muted-foreground">{workspace.slug}</div>
                  </div>
                </div>

                <div className="flex items-center justify-between border-t bg-muted/30 px-4 py-3">
                  <div />
                  <div className="flex items-center gap-2">
                    <Button asChild size="sm" variant="ghost">
                      <Link
                        aria-label={`Settings for ${workspace.name}`}
                        href={`/organizations/${organization.id}/workspaces/${workspace.id}/settings`}
                      >
                        <Settings className="size-4" />
                      </Link>
                    </Button>
                    <OpenWorkspaceButton
                      organizationId={workspace.organizationId}
                      workspaceId={workspace.id}
                    />
                  </div>
                </div>
              </div>
            ))}
          </div>
        </section>
      ) : (
        <div className="rounded-md border bg-card">
          <div className="flex min-h-64 items-center justify-center text-sm text-muted-foreground">
            Create an organization to begin.
          </div>
        </div>
      )}
    </AppShell>
  );
}
