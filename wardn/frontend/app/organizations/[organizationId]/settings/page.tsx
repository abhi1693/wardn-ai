import { notFound } from "next/navigation";

import { AppShell } from "@/app/components/app-shell";

import { getOrganization, getWorkspaceContext } from "../../data";
import { OrganizationForm } from "../../organization-form";

type OrganizationSettingsPageProps = {
  params: Promise<{ organizationId: string }>;
};

export default async function OrganizationSettingsPage({ params }: OrganizationSettingsPageProps) {
  const { organizationId } = await params;
  const [workspaceContext, organization] = await Promise.all([
    getWorkspaceContext(),
    getOrganization(organizationId),
  ]);
  if (!organization) {
    notFound();
  }

  return (
    <AppShell
      active="organization-settings"
      eyebrow="Organization"
      title={`${organization.name} settings`}
      workspaceContext={workspaceContext}
    >
      <OrganizationForm initialOrganization={organization} mode="edit" />
    </AppShell>
  );
}
