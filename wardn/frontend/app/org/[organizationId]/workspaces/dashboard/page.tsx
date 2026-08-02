import { List, Plus } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { AppShell } from "@/app/components/app-shell";
import { Button } from "@/components/ui/button";
import { OrganizationWorkspaces } from "@/components/organisms/organization-workspaces";
import type { OrganizationDashboardResponse } from "@/lib/api/generated/model";
import { backendJson } from "@/lib/api/server";
import { getWorkspaceContext } from "@/lib/workspace-context";

type OrganizationWorkspacesDashboardPageProps = {
  params: Promise<{ organizationId: string }>;
};

async function getOrganizationDashboard(organizationId: string) {
  return backendJson<OrganizationDashboardResponse>(
    `/api/v1/organizations/${encodeURIComponent(organizationId)}/dashboard?breakdownLimit=100`
  );
}

export default async function OrganizationWorkspacesDashboardPage({
  params,
}: OrganizationWorkspacesDashboardPageProps) {
  const { organizationId } = await params;
  const workspaceContext = await getWorkspaceContext({ organizationId });
  const organization = workspaceContext.selectedOrganization;
  const workspaces = workspaceContext.workspaces;

  if (!organization) {
    notFound();
  }

  const dashboard = await getOrganizationDashboard(organization.id);

  return (
    <AppShell
      active="workspaces-dashboard"
      actions={
        <>
          <Button asChild size="sm" variant="outline">
            <Link href={`/org/${encodeURIComponent(organization.id)}/workspaces`}>
              <List className="size-4" />
              Workspaces
            </Link>
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
      title="Workspace Dashboard"
      workspaceContext={workspaceContext}
    >
      <OrganizationWorkspaces
        dashboard={dashboard}
        organization={organization}
        workspaces={workspaces}
      />
    </AppShell>
  );
}
