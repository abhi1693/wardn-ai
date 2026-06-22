import { AppShell } from "@/app/components/app-shell";
import {
  getWorkspaceContext,
  workspaceInstallPath,
} from "@/lib/workspace-context";

import { ServerForm } from "@/app/registry/server-form";

type NewOrganizationRegistryServerPageProps = {
  params: Promise<{ organizationId: string }>;
};

export default async function NewOrganizationRegistryServerPage({
  params,
}: NewOrganizationRegistryServerPageProps) {
  const { organizationId } = await params;
  const workspaceContext = await getWorkspaceContext({ organizationId });

  return (
    <AppShell
      active="registry"
      eyebrow="MCP Registry"
      title="Add server"
      workspaceContext={workspaceContext}
    >
      <ServerForm
        createSuccessPath={`/org/${encodeURIComponent(organizationId)}/registry`}
        installBasePath={workspaceInstallPath(workspaceContext)}
        mode="create"
      />
    </AppShell>
  );
}
