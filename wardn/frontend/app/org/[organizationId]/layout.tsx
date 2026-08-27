import { notFound } from "next/navigation";
import type { ReactNode } from "react";

import { PersistentAppShell } from "@/components/templates/app-shell";
import { getWorkspaceContext } from "@/lib/workspace-context";

type OrganizationLayoutProps = {
  children: ReactNode;
  params: Promise<{ organizationId: string }>;
};

export default async function OrganizationLayout({ children, params }: OrganizationLayoutProps) {
  const { organizationId } = await params;
  const workspaceContext = await getWorkspaceContext({ organizationId });

  if (!workspaceContext.selectedOrganization) {
    notFound();
  }

  return (
    <PersistentAppShell workspaceContext={workspaceContext}>{children}</PersistentAppShell>
  );
}
