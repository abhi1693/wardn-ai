import { notFound } from "next/navigation";
import { Save } from "lucide-react";

import { AppShell } from "@/app/components/app-shell";
import { Button } from "@/components/ui/button";

import { getOrganization, getWorkspaceContext } from "../../data";
import { OrganizationForm } from "../../organization-form";

type OrganizationSettingsPageProps = {
  params: Promise<{ organizationId: string }>;
};

export default async function OrganizationSettingsPage({ params }: OrganizationSettingsPageProps) {
  const { organizationId } = await params;
  const formId = "organization-settings-form";
  const [workspaceContext, organization] = await Promise.all([
    getWorkspaceContext({ organizationId }),
    getOrganization(organizationId),
  ]);
  if (!organization) {
    notFound();
  }

  return (
    <AppShell
      active="organization-settings"
      actions={
        <Button form={formId} size="sm" type="submit">
          <Save className="size-4" />
          Save Changes
        </Button>
      }
      eyebrow="Organization"
      title="Settings"
      workspaceContext={workspaceContext}
    >
      <OrganizationForm formId={formId} initialOrganization={organization} mode="edit" />
    </AppShell>
  );
}
