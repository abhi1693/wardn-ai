import { AppShell } from "@/components/templates/app-shell";

import { getWorkspaceContext } from "../data";
import { OrganizationForm } from "../organization-form";

export default async function NewOrganizationPage() {
  const workspaceContext = await getWorkspaceContext();

  return (
    <AppShell
      active="organizations"
      eyebrow="Administration"
      title="New Organization"
      workspaceContext={workspaceContext}
    >
      <OrganizationForm mode="create" />
    </AppShell>
  );
}
