import { Plus } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { AppShell } from "@/app/components/app-shell";
import { Button } from "@/components/ui/button";
import { getOrganization, getWorkspaces } from "@/app/organizations/data";
import { getWorkspaceContext } from "@/lib/workspace-context";

import { WorkspacesOverviewClient } from "./workspaces-overview-client";

type OrganizationWorkspacesPageProps = {
  params: Promise<{ organizationId: string }>;
};

export default async function OrganizationWorkspacesPage({
  params,
}: OrganizationWorkspacesPageProps) {
  const { organizationId } = await params;
  const [workspaceContext, organization, workspaces] = await Promise.all([
    getWorkspaceContext({ organizationId }),
    getOrganization(organizationId),
    getWorkspaces(organizationId),
  ]);

  if (!organization) {
    notFound();
  }

  return (
    <AppShell
      active="workspaces"
      actions={
        <>
          <Button asChild size="sm" variant="outline">
            <Link href="/org">Change organization</Link>
          </Button>
          <Button asChild size="sm">
            <Link href={`/organizations/${organization.id}/workspaces/new`}>
              <Plus className="size-4" />
              New workspace
            </Link>
          </Button>
        </>
      }
      eyebrow="Organization"
      title="Workspaces"
      workspaceContext={workspaceContext}
    >
      <WorkspacesOverviewClient organization={organization} workspaces={workspaces} />
    </AppShell>
  );
}
