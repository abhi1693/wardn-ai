import { notFound } from "next/navigation";

import { AppShell } from "@/components/templates/app-shell";
import { ScheduledTasksClient } from "@/app/org/[organizationId]/workspace/[workspaceId]/scheduled-tasks/scheduled-tasks-client";
import type {
  ChatProviderConnectionListResponse,
  WorkspaceScheduledTaskListResponse,
  WorkspaceScheduledTaskRunListResponse,
} from "@/lib/api/generated/model";
import { backendJson } from "@/lib/api/server";
import { getWorkspaceContext } from "@/lib/workspace-context";

type ScheduledTasksPageProps = {
  params: Promise<{ organizationId: string; workspaceId: string }>;
};

async function getScheduledTasks(organizationId: string, workspaceId: string) {
  const payload = await backendJson<WorkspaceScheduledTaskListResponse>(
    `/api/v1/organizations/${encodeURIComponent(
      organizationId
    )}/workspaces/${encodeURIComponent(workspaceId)}/scheduled-tasks`
  );
  return payload.tasks;
}

async function getScheduledTaskRuns(organizationId: string, workspaceId: string) {
  const payload = await backendJson<WorkspaceScheduledTaskRunListResponse>(
    `/api/v1/organizations/${encodeURIComponent(
      organizationId
    )}/workspaces/${encodeURIComponent(workspaceId)}/scheduled-tasks/runs?limit=12`
  );
  return payload.runs;
}

async function getProviderConnections(organizationId: string, workspaceId: string) {
  const payload = await backendJson<ChatProviderConnectionListResponse>(
    `/api/v1/organizations/${encodeURIComponent(
      organizationId
    )}/workspaces/${encodeURIComponent(workspaceId)}/chat-providers`
  );
  return payload.connections;
}

export default async function ScheduledTasksPage({ params }: ScheduledTasksPageProps) {
  const { organizationId, workspaceId } = await params;
  const [workspaceContext, tasks, runs, connections] = await Promise.all([
    getWorkspaceContext({ organizationId, workspaceId }),
    getScheduledTasks(organizationId, workspaceId),
    getScheduledTaskRuns(organizationId, workspaceId),
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
      eyebrow="Workspace"
      title="Scheduled Tasks"
      workspaceContext={workspaceContext}
    >
      <ScheduledTasksClient
        connections={connections}
        organizationId={organization.id}
        runs={runs}
        tasks={tasks}
        workspaceId={workspace.id}
      />
    </AppShell>
  );
}
