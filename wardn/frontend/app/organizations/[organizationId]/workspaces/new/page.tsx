import { notFound } from "next/navigation";

import { AppShell } from "@/app/components/app-shell";

import { getWorkspaceContext } from "../../../data";
import { WorkspaceForm } from "../../../workspace-form";

type NewWorkspacePageProps = {
  params: Promise<{ organizationId: string }>;
};

export default async function NewWorkspacePage({ params }: NewWorkspacePageProps) {
  const { organizationId } = await params;
  const workspaceContext = await getWorkspaceContext({ organizationId });
  const organization = workspaceContext.selectedOrganization;
  if (!organization) {
    notFound();
  }

  return (
    <AppShell
      active="organizations"
      eyebrow="Organization"
      title={`Add workspace to ${organization.name}`}
      workspaceContext={workspaceContext}
    >
      <WorkspaceForm mode="create" organizationId={organization.id} />
    </AppShell>
  );
}
