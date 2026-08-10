import { notFound } from "next/navigation";

import { AppShell } from "@/components/templates/app-shell";
import { OrganizationDashboard } from "@/components/organisms/organization-dashboard";
import type { OrganizationDashboardResponse } from "@/lib/api/generated/model";
import { backendJson } from "@/lib/api/server";
import { getWorkspaceContext } from "@/lib/workspace-context";

type OrganizationDashboardPageProps = {
  params: Promise<{ organizationId: string }>;
};

async function getOrganizationDashboard(organizationId: string) {
  return backendJson<OrganizationDashboardResponse>(
    `/api/v1/organizations/${encodeURIComponent(organizationId)}/dashboard`
  );
}

export default async function OrganizationDashboardPage({
  params,
}: OrganizationDashboardPageProps) {
  const { organizationId } = await params;
  const workspaceContext = await getWorkspaceContext({ organizationId });
  const organization = workspaceContext.selectedOrganization;

  if (!organization) {
    notFound();
  }

  const dashboard = await getOrganizationDashboard(organization.id);

  return (
    <AppShell
      active="org-dashboard"
      eyebrow="Organization"
      title="Dashboard"
      workspaceContext={workspaceContext}
    >
      <OrganizationDashboard dashboard={dashboard} organization={organization} />
    </AppShell>
  );
}
