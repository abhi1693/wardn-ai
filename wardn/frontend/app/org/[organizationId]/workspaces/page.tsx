import { Plus } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { AppShell } from "@/components/templates/app-shell";
import { Button } from "@/components/atoms/button";
import { OrganizationWorkspacesList } from "@/components/organisms/organization-workspaces-list";
import { getWorkspaceContext } from "@/lib/workspace-context";

type OrganizationWorkspacesPageProps = {
  params: Promise<{ organizationId: string }>;
};

export default async function OrganizationWorkspacesPage({
  params,
}: OrganizationWorkspacesPageProps) {
  const { organizationId } = await params;
  const workspaceContext = await getWorkspaceContext({ organizationId });
  const organization = workspaceContext.selectedOrganization;
  const workspaces = workspaceContext.workspaces;

  if (!organization) {
    notFound();
  }

  return (
    <AppShell
      active="workspaces"
      actions={
        <Button asChild size="sm">
          <Link href={`/organizations/${organization.id}/workspaces/new`}>
            <Plus className="size-4" />
            New workspace
          </Link>
        </Button>
      }
      eyebrow="Organization"
      title="Workspaces"
      workspaceContext={workspaceContext}
    >
      <OrganizationWorkspacesList organization={organization} workspaces={workspaces} />
    </AppShell>
  );
}
