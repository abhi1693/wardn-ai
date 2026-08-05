import { notFound } from "next/navigation";

import { AppShell } from "@/app/components/app-shell";
import { ScheduledTaskFormClient } from "@/app/org/[organizationId]/workspace/[workspaceId]/scheduled-tasks/scheduled-tasks-client";
import type { ChatProviderConnectionListResponse } from "@/lib/api/generated/model";
import { backendJson } from "@/lib/api/server";
import { getWorkspaceContext } from "@/lib/workspace-context";

type NewScheduledTaskPageProps = {
  params: Promise<{ organizationId: string; workspaceId: string }>;
};

async function getProviderConnections(organizationId: string, workspaceId: string) {
  const payload = await backendJson<ChatProviderConnectionListResponse>(
    `/api/v1/organizations/${encodeURIComponent(
      organizationId
    )}/workspaces/${encodeURIComponent(workspaceId)}/chat-providers`
  );
  return payload.connections;
}

export default async function NewScheduledTaskPage({ params }: NewScheduledTaskPageProps) {
  const { organizationId, workspaceId } = await params;
  const [workspaceContext, connections] = await Promise.all([
    getWorkspaceContext({ organizationId, workspaceId }),
    getProviderConnections(organizationId, workspaceId),
  ]);
  const organization = workspaceContext.selectedOrganization;
  const workspace = workspaceContext.selectedWorkspace;

  if (!organization || !workspace) {
    notFound();
  }

  return (
    <AppShell
      active="workspace-scheduled-tasks"
      contentClassName="max-w-none px-8 max-md:px-4"
      contentInnerClassName="space-y-0"
      eyebrow="Workspace"
      title="New Scheduled Task"
      workspaceContext={workspaceContext}
    >
      <ScheduledTaskFormClient
        connections={connections}
        organizationId={organization.id}
        workspaceId={workspace.id}
      />
    </AppShell>
  );
}
